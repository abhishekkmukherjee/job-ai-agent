"""Resume tailoring, grounding checks, question answering and the prepare endpoints (fake AI)."""
from pathlib import Path

import pytest
from sqlalchemy import select

from app.agents.application_preparer import ApplicationPreparer
from app.agents.question_answerer import DEFAULT_QUESTIONS, QuestionAnswerer
from app.agents.resume_tailor import ResumeTailor, TailoringFailed, ground_resume
from app.ai.base import AITransientError
from app.ai.fake import FakeProvider
from app.ai.router import AIRouter
from app.config import Settings
from app.models import Job, Profile
from app.schemas.ai import TailoredResume

RESUME = {
    "headline": "AI Engineer - LLM applications",
    "summary": "Software engineer with 3 years building LLM/RAG systems.",
    "skills": ["Python", "RAG", "FastAPI", "Kubernetes", "Rust"],
    "experience": [
        {"title": "AI / Software Engineer", "company": "(fill in from your resume)", "start": "2020", "end": "2099",
         "bullets": ["Built production RAG pipelines and AI agents", "Cut latency by 45% across 12 services"]},
        {"title": "Staff Engineer", "company": "Google", "bullets": ["Led a team of 40"]},
    ],
    "projects": [
        {"name": "AI Job Application Agent", "description": "Personal AI assistant for job search.", "technologies": ["Python", "Playwright", "Terraform"]},
        {"name": "Mars Rover", "description": "invented", "technologies": ["C++"]},
    ],
    "education": ["PhD - MIT (2010)"],
    "certifications": ["AWS Solutions Architect"],
    "achievements": ["Won Nobel prize"],
    "tailoring_notes": ["Reordered skills to lead with LLM/RAG"],
}


def answers_for(prompt, system):
    qs = [line.split(". ", 1)[1] for line in prompt.split("=== QUESTIONS ===")[1].strip().splitlines() if ". " in line]
    out = []
    for q in qs:
        if "salary" in q.lower():
            out.append({"question": q, "answer": "", "confidence": 0.2, "needs_review": True})
        else:
            out.append({"question": q, "answer": f"Answer to: {q}", "confidence": 0.9, "needs_review": False})
    return {"answers": out}


def responder(prompt, system):
    if "=== QUESTIONS ===" in prompt:
        return answers_for(prompt, system)
    return RESUME


def make(responder=responder):
    settings = Settings(
        ai_backoff_base=0.001, ai_backoff_max=0.002, ai_max_retries=2, ai_route_resume_tailoring="fake",
        ai_route_application_questions="fake", ai_route_job_analysis="fake", ai_route_classification="fake", ai_route_fallback="",
    )
    provider = FakeProvider(responder)
    router = AIRouter({"fake": provider}, settings)
    tailor = ResumeTailor(router, settings)
    answerer = QuestionAnswerer(router, settings)
    return tailor, answerer, ApplicationPreparer(tailor, answerer), provider


def nimbus(db) -> Job:
    return db.execute(select(Job).where(Job.company == "Nimbus Labs")).scalars().one()


def test_ground_resume_removes_invented_facts(db):
    profile = db.execute(select(Profile)).scalars().one()
    resume, removed = ground_resume(TailoredResume.model_validate(RESUME), profile)
    assert "Kubernetes" not in resume.skills and "Rust" not in resume.skills
    assert "Python" in resume.skills and "RAG" in resume.skills
    assert [e.company for e in resume.experience] == ["(fill in from your resume)"]
    assert resume.experience[0].end == "Present" and resume.experience[0].start == ""   # dates come from the profile
    assert resume.experience[0].bullets == ["Built production RAG pipelines and AI agents"]  # 45% / 12 removed
    assert [p.name for p in resume.projects] == ["AI Job Application Agent"]
    assert "Terraform" not in resume.projects[0].technologies
    assert resume.education == [] and resume.certifications == [] and resume.achievements == []
    assert any("Grounding check removed" in n for n in resume.tailoring_notes)
    assert len(removed) == 7


def test_ground_resume_keeps_supported_numbers(db):
    profile = db.execute(select(Profile)).scalars().one()
    r = TailoredResume.model_validate({"summary": "About 3 years of experience with LLMs", "skills": ["LLM applications"]})
    r, removed = ground_resume(r, profile)
    assert r.summary.startswith("About 3 years") and removed == []


async def test_tailor_for_job_creates_application_and_pdf(db):
    tailor, _, _, provider = make()
    job = nimbus(db)
    app, resume = await tailor.tailor_for_job(db, job)
    assert app.job_id == job.id and app.status.value == "APPROVED"
    assert app.resume_version == "tailored-v1" and Path(app.resume_path).exists()
    assert Path(app.resume_path).read_bytes()[:4] == b"%PDF"
    assert app.tailored_resume["skills"][0] == "Python"
    # cached on second call, new PDF version
    app2, _ = await tailor.tailor_for_job(db, job)
    assert app2.id == app.id and app2.resume_version == "tailored-v2" and len(provider.calls) == 1
    await tailor.tailor_for_job(db, job, force=True)
    assert len(provider.calls) == 2


async def test_tailor_failure(db):
    tailor, _, _, _ = make(lambda p, s: AITransientError("down"))
    with pytest.raises(TailoringFailed):
        await tailor.generate(db, nimbus(db))


async def test_answerer_flags_missing_profile_facts(db):
    _, answerer, _, provider = make()
    job = nimbus(db)
    answers = await answerer.answer(db, job, DEFAULT_QUESTIONS)
    assert len(answers) == len(DEFAULT_QUESTIONS)
    by_q = {a.question: a for a in answers}
    assert by_q["What are your salary expectations?"].needs_review is True
    assert by_q["What is your notice period?"].needs_review is True      # profile notice period is empty
    assert by_q["Why do you want this role?"].needs_review is False
    assert by_q["What is your work authorization status?"].needs_review is False
    await answerer.answer(db, job, DEFAULT_QUESTIONS)
    assert len(provider.calls) == 1  # cached


async def test_prepare_endpoint_flow(client, db):
    from app.main import app as fastapi_app

    tailor, answerer, preparer, provider = make()
    fastapi_app.state.resume_tailor = tailor
    fastapi_app.state.application_preparer = preparer
    job_id = nimbus(db).id

    r = client.post(f"/api/jobs/{job_id}/tailor-resume")
    assert r.status_code == 200, r.text
    app_id = r.json()["application_id"]
    assert r.json()["resume"]["headline"]

    r = client.post(f"/api/applications/{app_id}/prepare", json={"questions": ["Why do you want this role?", "What are your salary expectations?"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "READY_TO_APPLY"
    assert body["has_resume_pdf"] is True
    assert len(body["answers"]) == 2 and body["answers"][1]["needs_review"] is True
    assert client.get(f"/api/applications/{app_id}/resume.pdf").status_code == 200

    # user edits an answer -> preserved on re-prepare
    edited = [dict(a, answer="My own words", needs_review=False) for a in body["answers"]]
    client.patch(f"/api/applications/{app_id}", json={"answers": edited})
    r = client.post(f"/api/applications/{app_id}/prepare", json={"questions": ["Why do you want this role?"]})
    assert r.json()["answers"][0]["answer"] == "My own words"

    r = client.post(f"/api/applications/{app_id}/answer-questions", json={"questions": ["Describe a hard bug you fixed."]})
    assert r.status_code == 200
    assert any(a["question"] == "Describe a hard bug you fixed." for a in r.json()["answers"])
    assert client.get("/api/dashboard").json()["counts"]["ready_to_apply"] == 1


async def test_prepare_endpoint_reports_ai_failure(client, db):
    from app.main import app as fastapi_app

    _, _, preparer, _ = make(lambda p, s: AITransientError("provider down"))
    fastapi_app.state.application_preparer = preparer
    job_id = nimbus(db).id
    app = client.post("/api/applications", json={"job_id": job_id, "status": "APPROVED"}).json()
    r = client.post(f"/api/applications/{app['id']}/prepare", json={})
    assert r.status_code == 502 and "provider down" in r.json()["detail"]
    assert client.get(f"/api/applications/{app['id']}").json()["status"] == "APPROVED"


async def test_profile_change_regenerates_answers_but_keeps_user_edits(client, db):
    from app.main import app as fastapi_app

    calls = {"n": 0}

    def responder(prompt, system):
        if "=== QUESTIONS ===" in prompt:
            calls["n"] += 1
            out = answers_for(prompt, system)
            for a in out["answers"]:
                if a["answer"]:
                    a["answer"] = f"{a['answer']} (v{calls['n']})"
            return out
        return RESUME

    tailor, answerer, preparer, provider = make(responder)
    fastapi_app.state.application_preparer = preparer
    fastapi_app.state.resume_tailor = tailor
    job_id = nimbus(db).id
    app_id = client.post("/api/applications", json={"job_id": job_id, "status": "APPROVED"}).json()["id"]
    qs = ["Why do you want this role?", "What is your notice period?"]
    body = client.post(f"/api/applications/{app_id}/prepare", json={"questions": qs}).json()
    assert body["answers"][0]["answer"].endswith("(v1)") and body["answers"][0]["source"] == "ai"
    # user edits only the first answer
    edited = [dict(body["answers"][0], answer="My own words"), body["answers"][1]]
    body = client.patch(f"/api/applications/{app_id}", json={"answers": edited}).json()
    assert body["answers"][0]["edited"] is True and body["answers"][1]["edited"] is False
    # profile changes -> cache miss -> generated answers refresh, the edited one stays
    client.patch("/api/profile", json={"notice_period": "60 days"})
    body = client.post(f"/api/applications/{app_id}/prepare", json={"questions": qs}).json()
    assert body["answers"][0]["answer"] == "My own words"
    assert body["answers"][1]["answer"].endswith("(v2)")
    # explicit override regenerates everything
    body = client.post(f"/api/applications/{app_id}/prepare", json={"questions": qs, "regenerate_answers": True}).json()
    assert body["answers"][0]["answer"].endswith("(v3)")


def test_ground_resume_tolerates_reworded_achievements(db):
    profile = db.execute(select(Profile)).scalars().one()
    profile.achievements = ["Writing: engineering articles covering RAG systems, async AI workloads and computer vision."]
    profile.certifications = ["AWS Certified Developer - Associate (2024)"]
    r = TailoredResume.model_validate({
        "achievements": ["Writing: engineering articles on RAG systems, async AI workloads and computer vision.", "Won a Nobel prize"],
        "certifications": ["AWS Certified Developer Associate", "CKA"],
    })
    r, removed = ground_resume(r, profile)
    assert r.achievements == profile.achievements and r.certifications == profile.certifications
    assert removed == ["certification 'CKA'", "achievement 'Won a Nobel prize'"]
