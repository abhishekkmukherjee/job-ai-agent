"""End-to-end browser test against the local fake application site (headless Chromium).

Skipped automatically when Playwright's Chromium is not installed.
"""
from pathlib import Path

import pytest
from sqlalchemy import select

from app.agents.question_answerer import QuestionAnswerer
from app.agents.resume_tailor import ResumeTailor
from app.ai.fake import FakeProvider
from app.ai.router import AIRouter
from app.browser.agent import BrowserAgent
from app.config import FAKE_JOB_SITE_DIR, Settings
from app.models import Application, ApplicationStatus, Job, Profile

pytestmark = pytest.mark.browser


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
        return True
    except Exception:
        return False


CHROMIUM = _chromium_available()


def filled_labels_ok(result) -> bool:
    labels = {f["label"] for f in result.fields if f["status"] == "filled"}
    return "Cover letter (optional)" in labels


def responder(prompt, system):
    if "=== QUESTIONS ===" in prompt:
        qs = [line.split(". ", 1)[1] for line in prompt.split("=== QUESTIONS ===")[1].strip().splitlines() if ". " in line]
        return {"answers": [{"question": q, "answer": f"Generated answer for: {q}", "confidence": 0.9, "needs_review": False} for q in qs]}
    return {"headline": "AI Engineer", "summary": "3 years of LLM work.", "skills": ["Python", "RAG"], "experience": [], "projects": []}


@pytest.mark.skipif(not CHROMIUM, reason="Playwright Chromium not installed (python -m playwright install chromium)")
async def test_fill_fake_application_form_without_submitting(db):
    settings = Settings(
        browser_headless=True, browser_keep_open=False, ai_route_application_questions="fake", ai_route_resume_tailoring="fake",
        ai_route_job_analysis="fake", ai_route_classification="fake", ai_route_fallback="", ai_backoff_base=0.001, ai_backoff_max=0.002,
    )
    router = AIRouter({"fake": FakeProvider(responder)}, settings)
    profile = db.execute(select(Profile)).scalars().one()
    profile.email, profile.phone, profile.notice_period, profile.expected_salary = "abhishek@example.com", "+91 9999999999", "30 days", "25 LPA"
    profile.linkedin_url, profile.github_url, profile.current_company = "https://linkedin.com/in/abhishek", "https://github.com/abhishek", "Acme"
    db.commit()
    job = db.execute(select(Job).where(Job.company == "Nimbus Labs")).scalars().one()
    tailor = ResumeTailor(router, settings)
    app, _ = await tailor.tailor_for_job(db, job)
    app.answers = [{"question": "Why do you want this role?", "answer": "Because I love LLM engineering.", "confidence": 0.9, "needs_review": False}]
    db.commit()

    agent = BrowserAgent(settings, QuestionAnswerer(router, settings))
    url = (FAKE_JOB_SITE_DIR / "index.html").resolve().as_uri()
    result = await agent.fill_application(db, app, url=url)

    assert result.ok, result.message
    assert result.resume_uploaded is True and result.resume.endswith(".pdf")
    assert result.fields_filled >= 12
    assert result.questions_answered == 3   # one prepared answer + two generated (about, cover letter)
    assert filled_labels_ok(result)
    filled = {f["label"]: f for f in result.fields}
    assert filled["First name"]["value"] == "Abhishek" and filled["Last name"]["value"] == "Mukherjee"
    assert filled["Email address"]["value"] == "abhishek@example.com"
    assert filled["Notice period"]["value"] == "30 days" and filled["Notice period"]["status"] == "filled"
    assert filled["Why do you want this role?"]["value"].startswith("Because I love")
    assert filled["Tell us about yourself"]["value"].startswith("Generated answer")
    unmatched = {f["label"] for f in result.unmatched_fields}
    assert "I agree to the privacy policy" not in unmatched  # consent is ticked so the form can be submitted
    assert filled["I agree to the privacy policy"]["action"] == "check"
    assert filled["Are you legally authorized to work in India?"]["value"] == "Yes"
    assert "NOT submitted" in result.message and "WARNING" not in result.message
    assert result.browser_open is False and agent.sessions == {}

    db.refresh(app)
    assert app.status == ApplicationStatus.READY_TO_APPLY
    assert app.fill_result["fields_filled"] == result.fields_filled
    assert any(a["question"] == "Tell us about yourself" for a in app.answers)


@pytest.mark.skipif(not CHROMIUM, reason="Playwright Chromium not installed")
async def test_fill_rejects_bad_url_and_handles_navigation_errors(db):
    settings = Settings(browser_headless=True, browser_keep_open=False)
    agent = BrowserAgent(settings, None)
    job = db.execute(select(Job).where(Job.company == "Nimbus Labs")).scalars().one()
    app = Application(job_id=job.id, company=job.company, role=job.title, job_url="javascript:alert(1)", status=ApplicationStatus.APPROVED)
    db.add(app)
    db.commit()
    with pytest.raises(ValueError):
        await agent.fill_application(db, app)
    result = await agent.fill_application(db, app, url="http://127.0.0.1:9/does-not-exist")
    assert result.ok is False and "Browser fill failed" in result.message
    assert agent.sessions == {}
