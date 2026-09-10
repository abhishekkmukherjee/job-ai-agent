"""Guarded auto-apply: field-mapper guards, pipeline stage with a fake browser agent, real browser run on the fake site."""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.browser.field_mapper import FormField, map_fields, salary_value, submit_blockers
from app.config import FAKE_JOB_SITE_DIR, Settings
from app.models import Application, ApplicationStatus, Job, JobPipelineStatus, Profile, Recommendation, RemoteType
from app.schemas.application import FillResponse
from app.schemas.settings import AutoApplySettings, RuntimeSettingsUpdate
from app.services.settings_service import update_runtime_settings


def profile_of(db) -> Profile:
    p = db.execute(select(Profile)).scalars().one()
    p.current_salary = 240000
    p.salary_expectation_remote = 650000
    p.salary_expectation_onsite = 700000
    p.notice_period = "30 days"
    p.email = "a@b.com"
    p.phone = "+91 9"
    db.commit()
    return p


def ff(kind, label, required=False, options=None, name=""):
    return FormField(selector=f"[x='{label}']", kind=kind, label=label, required=required, options=options or [], name=name)


def test_salary_value_by_work_mode(db):
    p = profile_of(db)
    assert salary_value(p, "remote", numeric=True) == "650000"
    assert salary_value(p, "onsite", numeric=False) == "7 LPA (INR)"
    assert salary_value(p, None, numeric=False) == "7 LPA (INR)"
    assert salary_value(p, "remote", numeric=False, current=True) == "2.4 LPA (INR)"
    p.salary_expectation_remote = None
    assert salary_value(p, "remote", numeric=True) == "700000"


def test_mapper_fills_salary_consent_and_leaves_marketing(db):
    p = profile_of(db)
    fields = [
        ff("number", "Expected salary (annual)"), ff("text", "Current CTC"),
        ff("checkbox", "I agree to the privacy policy", required=True), ff("checkbox", "Send me marketing updates"),
        ff("select", "Are you legally authorized to work in India?", options=["Select...", "Yes", "No"]),
    ]
    actions, questions, unmatched = map_fields(fields, p, None, "", job_remote_type="remote")
    by_label = {a.field.label: a for a in actions}
    assert by_label["Expected salary (annual)"].value == "650000"
    assert by_label["Current CTC"].value == "2.4 LPA (INR)"
    assert by_label["I agree to the privacy policy"].action == "check"
    assert by_label["Are you legally authorized to work in India?"].value == "Yes"
    assert [f.label for f in unmatched] == ["Send me marketing updates"]


def test_submit_blockers():
    a_ok = ff("text", "Email", required=True)
    a_req_unmatched = ff("text", "Passport number", required=True)
    from app.browser.field_mapper import FillAction

    actions = [FillAction(a_ok, "fill", "x", "profile", status="filled"), FillAction(ff("file", "Resume"), "upload", "r.pdf", "resume", status="uploaded")]
    assert submit_blockers(actions, [], ["Submit"], captcha=False, fields_total=2) == []
    assert "CAPTCHA" in submit_blockers(actions, [], ["Submit"], captcha=True, fields_total=2)[0]
    assert "no submit button" in submit_blockers(actions, [], [], captcha=False, fields_total=2)[0]
    assert "required field not filled: Passport number" in submit_blockers(actions, [a_req_unmatched], ["Submit"], False, 2)[0]
    assert submit_blockers(actions, [ff("text", "Optional thing")], ["Submit"], False, 2) == []
    failed = FillAction(a_ok, "fill", "x", "profile", status="failed")
    assert any("required field failed" in b for b in submit_blockers([failed], [], ["Submit"], False, 1))


# --------------------------------------------------------------------------- pipeline stage
class FakeBrowserAgent:
    def __init__(self, submitted=True, blockers=None):
        self.submitted, self.blockers, self.calls = submitted, blockers or [], []

    async def fill_application(self, db, app, url=None, headless=None, submit=False):
        self.calls.append((app.id, submit, headless))
        from app.services import application_service

        if self.submitted and submit:
            application_service.transition_status(db, app, ApplicationStatus.APPLIED, note="auto-submitted by the browser agent")
        app.fill_result = {"auto_submit": submit, "submitted": self.submitted}
        db.commit()
        return FillResponse(ok=True, message="filled", fields_filled=5, questions_answered=2, resume_uploaded=True, submitted=self.submitted, submit_evidence="success message", blockers=self.blockers)


class FakePreparer:
    def __init__(self, needs_review=False):
        self.needs_review, self.calls = needs_review, []

    async def prepare(self, db, app, questions=None, regenerate_resume=False):
        self.calls.append(app.id)
        app.answers = [{"question": "Why?", "answer": "Because", "needs_review": self.needs_review, "confidence": 0.9}]
        app.resume_version = "tailored-v1"
        app.status = ApplicationStatus.READY_TO_APPLY
        db.commit()
        return app


class FakeNotifier:
    def __init__(self):
        self.events = []

    async def send_event(self, title, lines, link=None):
        self.events.append((title, lines, link))

    async def send_daily_report(self, db, run, stats):
        self.events.append(("report", [], None))


def scored_job(db, ext, title, company, url, score, remote=RemoteType.REMOTE) -> Job:
    job = Job(
        external_id=ext, source="fakeboard", title=title, company=company, url=url, apply_url=url, remote_type=remote,
        pipeline_status=JobPipelineStatus.ANALYZED, match_score=score, recommendation=Recommendation.APPLY if score >= 90 else Recommendation.REVIEW,
        analysis={"match_score": score, "profile_version": 1}, description="Python job",
    )
    db.add(job)
    db.commit()
    return job


def build_pipeline(db, browser, preparer, notifier, **auto):
    from app.jobs.pipeline import JobPipeline
    from app.jobs.sources.registry import SourceRegistry

    settings = Settings(job_sources_enabled="", ai_route_job_analysis="", ai_route_classification="", ai_route_fallback="", gemini_api_key="", openrouter_api_key="", groq_api_key="")
    update_runtime_settings(db, RuntimeSettingsUpdate(auto_apply=AutoApplySettings(enabled=True, min_score=85, daily_cap=2, **{"email_min_interval_seconds": 0, **auto})))
    return JobPipeline(SourceRegistry(settings, sources=[]), None, settings, notifier=notifier, preparer=preparer, browser_agent=browser)


async def test_auto_apply_submits_top_matches_within_cap_and_skips_blocked_domains(db):
    profile_of(db)
    j1 = scored_job(db, "1", "AI Engineer", "Great Co", "https://boards.greenhouse.io/greatco/jobs/1", 95)
    j2 = scored_job(db, "2", "Backend Engineer", "Fine Co", "https://jobs.lever.co/fineco/2", 90)
    j3 = scored_job(db, "3", "ML Engineer", "Third Co", "https://apply.workable.com/thirdco/j/3", 88)   # beyond the cap
    j4 = scored_job(db, "4", "AI Engineer", "Linked Co", "https://www.linkedin.com/jobs/view/4", 96)      # blocked domain
    scored_job(db, "5", "Data Engineer", "Low Co", "https://example.com/5", 70)                          # below min_score
    browser, preparer, notifier = FakeBrowserAgent(submitted=True), FakePreparer(), FakeNotifier()
    pipeline = build_pipeline(db, browser, preparer, notifier)
    run = await pipeline.run(db, trigger="test", analyze=True, notify=False)
    assert run.status.value == "COMPLETED", run.error
    assert run.stats["auto_applied"] == 2 and run.stats["auto_needs_review"] == 1
    assert sorted(preparer.calls) == sorted([a.id for a in db.query(Application).filter(Application.job_id.in_([j1.id, j2.id]))])
    statuses = {a.job_id: a.status for a in db.query(Application).all()}
    assert statuses[j1.id] == ApplicationStatus.APPLIED and statuses[j2.id] == ApplicationStatus.APPLIED
    assert statuses[j4.id] == ApplicationStatus.SHORTLISTED and j3.id not in statuses
    titles = [e[0] for e in notifier.events]
    assert any(t.startswith("Applied: AI Engineer at Great Co") for t in titles)
    assert any(t.startswith("Manual apply needed: AI Engineer at Linked Co") for t in titles)
    # second run the same day: cap reached, nothing re-attempted
    run2 = await pipeline.run(db, trigger="test", analyze=True, notify=False)
    assert run2.stats["auto_applied"] == 0 and run2.stats.get("auto_apply_skipped") == "daily cap reached"
    assert len(browser.calls) == 2


async def test_auto_apply_holds_back_when_answers_need_review_or_form_blocked(db):
    profile_of(db)
    job = scored_job(db, "7", "AI Engineer", "Review Co", "https://boards.greenhouse.io/reviewco/jobs/7", 93)
    browser, notifier = FakeBrowserAgent(submitted=True), FakeNotifier()
    pipeline = build_pipeline(db, browser, FakePreparer(needs_review=True), notifier)
    run = await pipeline.run(db, trigger="test", analyze=True)
    # A flagged answer no longer blocks by itself: the browser agent skips it and only a *required*
    # form field it cannot fill becomes a blocker.  With the fake browser reporting a clean submit, it applies.
    assert run.stats["auto_applied"] == 1 and browser.calls[0][1] is True
    app = db.query(Application).filter_by(job_id=job.id).one()
    assert app.status == ApplicationStatus.APPLIED and app.fill_result["auto_apply_attempted"] is True

    job2 = scored_job(db, "8", "AI Engineer", "Captcha Co", "https://boards.greenhouse.io/captchaco/jobs/8", 94)
    browser2 = FakeBrowserAgent(submitted=False, blockers=["CAPTCHA present (never bypassed)"])
    pipeline2 = build_pipeline(db, browser2, FakePreparer(), notifier)
    run2 = await pipeline2.run(db, trigger="test", analyze=True)
    assert run2.stats["auto_applied"] == 0 and browser2.calls[0][1] is True
    assert db.query(Application).filter_by(job_id=job2.id).one().status == ApplicationStatus.READY_TO_APPLY
    assert any("CAPTCHA" in line for line in notifier.events[-1][1])


async def test_auto_apply_disabled_by_default(db):
    profile_of(db)
    scored_job(db, "9", "AI Engineer", "Great Co", "https://boards.greenhouse.io/greatco/jobs/9", 99)
    from app.jobs.pipeline import JobPipeline
    from app.jobs.sources.registry import SourceRegistry

    settings = Settings(job_sources_enabled="", gemini_api_key="", openrouter_api_key="", groq_api_key="")
    browser = FakeBrowserAgent()
    pipeline = JobPipeline(SourceRegistry(settings, sources=[]), None, settings, preparer=FakePreparer(), browser_agent=browser)
    run = await pipeline.run(db, trigger="test", analyze=True)
    assert run.stats["auto_applied"] == 0 and browser.calls == []


# --------------------------------------------------------------------------- real browser on the fake site
@pytest.mark.browser
async def test_browser_agent_auto_submits_fake_site(db):
    from app.browser.agent import BrowserAgent
    from app.services import application_service
    from app.schemas.application import ApplicationCreate

    try:
        import playwright  # noqa: F401
    except ImportError:
        pytest.skip("playwright not installed")
    profile = profile_of(db)
    job = db.execute(select(Job).where(Job.company == "Nimbus Labs")).scalars().one()
    app = application_service.create_application(db, ApplicationCreate(job_id=job.id, status=ApplicationStatus.APPROVED))
    app.answers = [
        {"question": "Why do you want this role?", "answer": "Because it fits.", "needs_review": False, "confidence": 0.9},
        {"question": "Tell us about yourself", "answer": "Engineer.", "needs_review": False, "confidence": 0.9},
    ]
    db.commit()
    settings = Settings(browser_headless=True, browser_keep_open=False, browser_timeout_ms=15000)
    agent = BrowserAgent(settings, answerer=None)
    url = (FAKE_JOB_SITE_DIR / "index.html").resolve().as_uri()
    try:
        result = await agent.fill_application(db, app, url=url, submit=True)
    except RuntimeError as e:
        pytest.skip(str(e))
    assert result.ok, result.message
    assert result.blockers == [], result.blockers
    assert result.submitted is True and "submitted" in result.submit_evidence
    assert result.captcha_detected is False
    db.refresh(app)
    assert app.status == ApplicationStatus.APPLIED and app.applied_at is not None
    assert app.fill_result["auto_submit"] is True
    # consent checkbox was ticked, salary filled from the structured expectation
    values = {f["label"]: f["value"] for f in result.fields}
    assert values["I agree to the privacy policy"] == "yes"
    assert values["Expected salary (annual)"].startswith("7")


# --------------------------------------------------------------------------- email channel
class FakeAnswerer:
    async def answer(self, db, job, questions, profile=None, force=False):
        from app.schemas.ai import QuestionAnswer

        return [QuestionAnswer(question=q, answer="Dear team, I am applying for this role. Regards, Abhishek", confidence=0.9, needs_review=False) for q in questions]


class FakeEmailApplier:
    def __init__(self, configured=True):
        self.configured, self.sent = configured, []

    def is_configured(self):
        return self.configured

    def recently_emailed_company(self, db, company, days):
        from app.services.email_apply import EmailApplier

        return EmailApplier.recently_emailed_company(db, company, days)  # the real guard, against the test DB

    def send(self, to_email, subject, body, resume_path, reply_to=None):
        self.sent.append({"to": to_email, "subject": subject, "body": body, "resume": resume_path, "company": subject.split(" - ")[0]})
        return {"channel": "email", "to": to_email, "subject": subject, "attachment": "resume.pdf"}


async def test_auto_apply_by_email_for_blocked_or_linkless_postings(db, tmp_path):
    profile_of(db)
    from app.jobs.pipeline import JobPipeline
    from app.jobs.sources.registry import SourceRegistry

    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"%PDF")
    j1 = scored_job(db, "21", "AI Engineer", "Mail Co", "https://www.linkedin.com/jobs/view/21", 92)
    j1.description = "Great role. To apply, send your resume to careers@mailco.in"
    j2 = scored_job(db, "22", "Backend Engineer", "Mail Co", "https://www.naukri.com/job-listings-22", 90)
    j2.description = "Second opening at the same company - email hr@mailco.in"
    j3 = scored_job(db, "23", "AI Engineer", "NoMail Co", "https://www.linkedin.com/jobs/view/23", 91)
    db.commit()
    settings = Settings(job_sources_enabled="", gemini_api_key="", openrouter_api_key="", groq_api_key="")
    update_runtime_settings(db, RuntimeSettingsUpdate(auto_apply=AutoApplySettings(enabled=True, min_score=85, daily_cap=5, email_enabled=True)))
    preparer = FakePreparer()
    preparer.answerer = FakeAnswerer()

    async def prep(db_, app, questions=None, regenerate_resume=False):
        app = await FakePreparer.prepare(preparer, db_, app, questions, regenerate_resume)
        app.resume_path = str(pdf)
        db_.commit()
        return app

    preparer.prepare = prep
    emailer, notifier = FakeEmailApplier(), FakeNotifier()
    pipeline = JobPipeline(SourceRegistry(settings, sources=[]), None, settings, notifier=notifier, preparer=preparer, browser_agent=FakeBrowserAgent(), email_applier=emailer)
    run = await pipeline.run(db, trigger="test", analyze=True)
    assert run.status.value == "COMPLETED", run.error
    assert run.stats["auto_applied"] == 1 and run.stats.get("auto_emailed") == 1
    assert run.stats.get("auto_skipped_same_company") == 1          # second Mail Co posting within 7 days
    assert emailer.sent[0]["to"] == "careers@mailco.in" and emailer.sent[0]["resume"] == str(pdf)
    statuses = {a.job_id: a for a in db.query(Application).all()}
    assert statuses[j1.id].status == ApplicationStatus.APPLIED and statuses[j1.id].fill_result["channel"] == "email"
    assert statuses[j1.id].cover_note.startswith("Dear team")
    assert statuses[j3.id].status == ApplicationStatus.SHORTLISTED   # blocked domain, no email -> manual
    titles = [e[0] for e in notifier.events]
    assert any(t.startswith("Applied by email: AI Engineer at Mail Co") for t in titles)
    assert any(t.startswith("Manual apply needed: AI Engineer at NoMail Co") for t in titles)


def test_submit_blockers_require_application_shaped_form():
    from app.browser.field_mapper import FillAction

    email = FillAction(ff("email", "Email address"), "fill", "a@b.com", "profile", status="filled")
    upload = FillAction(ff("file", "Resume"), "upload", "r.pdf", "resume", status="uploaded")
    phone = FillAction(ff("tel", "Phone"), "fill", "1", "profile", status="filled")
    city = FillAction(ff("text", "City"), "fill", "Pune", "profile", status="filled")
    # newsletter-style box: one email field + submit -> never auto-submitted
    assert any("does not look like an application form" in b for b in submit_blockers([email], [], ["Subscribe"], False, 1))
    # email + resume upload -> fine
    assert submit_blockers([email, upload], [], ["Submit application"], False, 2) == []
    # email + 3 profile fields, no upload -> fine
    assert submit_blockers([email, phone, city], [], ["Submit"], False, 3) == []
    # upload but no identity field -> blocked
    assert any("does not look like" in b for b in submit_blockers([upload, phone], [], ["Submit"], False, 2))


async def test_email_daily_cap_and_pacing(db, monkeypatch):
    profile_of(db)
    scored_job(db, "41", "AI Engineer", "Mail A", "", 95).description = "Send your CV to hr@maila.com"
    scored_job(db, "42", "AI Engineer", "Mail B", "", 94).description = "Send your CV to hr@mailb.com"
    db.commit()
    sent = []

    class Applier:
        def is_configured(self):
            return True

        def recently_emailed_company(self, db_, company, days):
            return False

        def send(self, to, subject, body, resume_path, reply_to=None):
            sent.append(to)
            return {"channel": "email", "to": to, "subject": subject, "attachment": "r.pdf"}

    class Prep(FakePreparer):
        class answerer:  # noqa: N801 - mimics QuestionAnswerer.answer
            @staticmethod
            async def answer(db_, job, questions):
                from app.schemas.ai import QuestionAnswer

                return [QuestionAnswer(question=questions[0], answer="Hello, I would like to apply.", confidence=0.9, needs_review=False)]

    from app.jobs.pipeline import JobPipeline
    from app.jobs.sources.registry import SourceRegistry

    settings = Settings(job_sources_enabled="", gemini_api_key="", openrouter_api_key="", groq_api_key="")
    update_runtime_settings(db, RuntimeSettingsUpdate(auto_apply=AutoApplySettings(enabled=True, min_score=85, daily_cap=10, email_daily_cap=1, email_min_interval_seconds=0)))
    pipeline = JobPipeline(SourceRegistry(settings, sources=[]), None, settings, notifier=FakeNotifier(), preparer=Prep(), browser_agent=FakeBrowserAgent(), email_applier=Applier())
    for app in db.query(Application).all():
        app.resume_path = str(Path(__file__))  # any existing file
    run = await pipeline.run(db, trigger="test", analyze=True)
    assert run.status.value == "COMPLETED", run.error
    assert sent == ["hr@maila.com"] and run.stats["auto_emailed"] == 1 and run.stats.get("auto_email_cap_reached") is True
