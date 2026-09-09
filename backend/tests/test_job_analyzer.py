import json

import pytest
from sqlalchemy import select

from app.agents.job_analyzer import AnalysisFailed, JobAnalyzer, job_to_prompt_text
from app.ai.base import AITransientError
from app.ai.fake import FakeProvider
from app.ai.router import AIRouter
from app.config import Settings
from app.models import AIResult, Job, JobPipelineStatus, Profile

ANALYSIS = {
    "match_score": 92, "recommendation": "REJECT", "experience_match": 90, "skill_match": 95, "role_match": 95,
    "location_match": 100, "salary_match": 80, "reasoning": ["Strong LLM/RAG match"], "matched_skills": ["Python", "RAG"],
    "missing_requirements": ["Kubernetes"], "red_flags": [], "confidence": 0.9, "summary": "Great fit",
}


def make_analyzer(responder) -> tuple[JobAnalyzer, FakeProvider]:
    settings = Settings(ai_backoff_base=0.001, ai_backoff_max=0.002, ai_max_retries=2, ai_route_job_analysis="fake", ai_route_classification="fake", ai_route_fallback="")
    provider = FakeProvider(responder)
    router = AIRouter({"fake": provider}, settings)
    return JobAnalyzer(router, settings), provider


def first_job(db) -> Job:
    return db.execute(select(Job).where(Job.title.like("AI Engineer%"))).scalars().first()


def test_job_prompt_text_contains_key_fields(db):
    job = first_job(db)
    text = job_to_prompt_text(job, max_description_chars=50)
    assert "Title: AI Engineer" in text and "Nimbus Labs" in text and "truncated" in text


async def test_analyze_job_sets_fields_and_caches(db):
    analyzer, provider = make_analyzer(lambda p, s: ANALYSIS)
    job = first_job(db)
    result = await analyzer.analyze_job(db, job)
    assert result.match_score == 92
    assert result.recommendation.value == "APPLY"  # band enforced, model said REJECT
    assert job.pipeline_status == JobPipelineStatus.ANALYZED
    assert job.match_score == 92 and job.recommendation.value == "APPLY"
    assert job.analysis["matched_skills"] == ["Python", "RAG"]
    assert "Nimbus Labs" in provider.calls[0]["prompt"] and "Abhishek" in provider.calls[0]["prompt"]
    assert db.execute(select(AIResult)).scalars().one().task == "job_analysis"

    # second call -> cache hit, no new provider call
    job.match_score = None
    await analyzer.analyze_job(db, job)
    assert len(provider.calls) == 1 and job.match_score == 92

    # force -> new call
    await analyzer.analyze_job(db, job, force=True)
    assert len(provider.calls) == 2

    # profile change -> cache miss
    profile = db.execute(select(Profile)).scalars().one()
    profile.version += 1
    db.commit()
    await analyzer.analyze_job(db, job)
    assert len(provider.calls) == 3


async def test_analyze_job_failure_is_recorded(db):
    analyzer, provider = make_analyzer(lambda p, s: AITransientError("boom"))
    job = first_job(db)
    with pytest.raises(AnalysisFailed):
        await analyzer.analyze_job(db, job)
    assert job.pipeline_status == JobPipelineStatus.ANALYSIS_FAILED
    assert "boom" in job.analysis_error
    assert job.match_score is None


async def test_quick_filter_cached(db):
    analyzer, provider = make_analyzer(lambda p, s: json.dumps({"relevant": False, "reason": "intern", "confidence": 0.9}))
    job = db.execute(select(Job).where(Job.title.like("%Intern%"))).scalars().first()
    r1 = await analyzer.quick_filter(db, job)
    r2 = await analyzer.quick_filter(db, job)
    assert r1.relevant is False and r2.relevant is False
    assert len(provider.calls) == 1


async def test_analyze_endpoint_with_fake_provider(client, db, monkeypatch):
    from app.main import app

    analyzer, _ = make_analyzer(lambda p, s: ANALYSIS)
    app.state.job_analyzer = analyzer
    job_id = client.get("/api/jobs").json()["items"][0]["id"]
    r = client.post(f"/api/jobs/{job_id}/analyze")
    assert r.status_code == 200, r.text
    assert r.json()["match_score"] == 92
    assert client.get("/api/dashboard").json()["counts"]["recommended_applications"] == 1


async def test_analyze_endpoint_reports_failure(client, db):
    from app.main import app

    analyzer, _ = make_analyzer(lambda p, s: AITransientError("provider down"))
    app.state.job_analyzer = analyzer
    job_id = client.get("/api/jobs").json()["items"][0]["id"]
    r = client.post(f"/api/jobs/{job_id}/analyze")
    assert r.status_code == 502
    assert "provider down" in r.json()["detail"]
