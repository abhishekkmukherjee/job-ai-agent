"""Integration test of the discovery pipeline with a fake source and a fake AI provider."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.agents.job_analyzer import JobAnalyzer
from app.ai.base import AITransientError
from app.ai.fake import FakeProvider
from app.ai.router import AIRouter
from app.config import Settings
from app.jobs.pipeline import JobPipeline
from app.jobs.sources.base import JobSource, SearchContext, SourceError
from app.jobs.sources.registry import SourceRegistry
from app.models import Job, JobPipelineStatus, PipelineFailure, RemoteType, SearchRunStatus
from app.schemas.job import NormalizedJob

NOW = datetime.now(timezone.utc)


class FakeSource(JobSource):
    name = "fakeboard"
    description = "test source"

    def __init__(self, jobs, **kw):
        super().__init__(**kw)
        self._jobs = jobs

    async def fetch(self, ctx: SearchContext):
        return self._jobs


class BrokenSource(JobSource):
    name = "broken"

    async def fetch(self, ctx: SearchContext):
        raise SourceError("broken: HTTP 500")


def nj(ext, title, company, desc="Python, LLM, RAG. 2-4 years experience.", location="Remote", remote=RemoteType.REMOTE, url=""):
    return NormalizedJob(
        external_id=ext, source="fakeboard", title=title, company=company, description=desc, location=location,
        remote_type=remote, url=url or f"https://fakeboard.example/{ext}", posted_at=NOW - timedelta(days=1),
    )


def analysis_for(prompt, system):
    score = 93 if "Nimbus" in prompt or "Great Co" in prompt else 70
    return {"match_score": score, "recommendation": "APPLY", "reasoning": ["ok"], "matched_skills": ["Python"], "confidence": 0.8}


def build(settings=None, responder=analysis_for, sources=None):
    settings = settings or Settings(
        ai_backoff_base=0.001, ai_backoff_max=0.002, ai_max_retries=2, ai_route_job_analysis="fake",
        ai_route_classification="fake", ai_route_fallback="", job_sources_enabled="fakeboard,broken",
    )
    provider = FakeProvider(responder)
    analyzer = JobAnalyzer(AIRouter({"fake": provider}, settings), settings)
    registry = SourceRegistry(settings, sources=sources)
    return JobPipeline(registry, analyzer, settings), provider


async def test_pipeline_end_to_end(db):
    jobs = [
        nj("1", "AI Engineer", "Great Co"),
        nj("2", "Machine Learning Intern", "Intern Co"),
        nj("3", "AI Engineer (LLM Applications)", "Nimbus Labs"),          # duplicate of a sample job
        nj("4", "Engineer II", "Mystery Co", desc="Build RAG pipelines with Python and LLMs"),  # unsure -> AI filter
        nj("5", "Senior Backend Engineer", "Old Co", desc="Requires 9+ years of experience"),
        nj("1", "AI Engineer", "Great Co"),                                 # exact duplicate within the batch
    ]

    def responder(prompt, system):
        if "fast job-relevance classifier" in prompt:
            return {"relevant": "Mystery" in prompt, "reason": "relevant stack", "confidence": 0.7}
        return analysis_for(prompt, system)

    pipeline, provider = build(responder=responder, sources=[FakeSource(jobs), BrokenSource()])
    run = await pipeline.run(db, trigger="test", analyze=True)

    assert run.status == SearchRunStatus.COMPLETED, run.error
    s = run.stats
    assert s["sources"]["fakeboard"]["fetched"] == 6
    assert "HTTP 500" in s["sources"]["broken"]["error"]
    assert s["new_jobs"] == 4                 # 1,2,4,5 (3 dup of sample, second 1 dup)
    assert s["duplicates"] == 2
    # rule filter processed the 4 new jobs + 7 sample jobs
    by_company = {j.company: j for j in db.execute(select(Job).where(Job.duplicate_of_id.is_(None))).scalars().all()}
    assert by_company["Intern Co"].pipeline_status == JobPipelineStatus.REJECTED_BY_RULES
    assert by_company["Old Co"].pipeline_status == JobPipelineStatus.REJECTED_BY_RULES
    assert by_company["Mystery Co"].pipeline_status == JobPipelineStatus.ANALYZED  # AI filter said relevant
    assert by_company["Great Co"].match_score == 93
    assert by_company["Nimbus Labs"].match_score == 93  # sample job analyzed too
    assert s["analyzed"] >= 5 and s["strong_matches"] >= 2
    dup_rows = db.execute(select(Job).where(Job.duplicate_of_id.isnot(None))).scalars().all()
    assert len(dup_rows) == 1 and dup_rows[0].duplicate_of_id == by_company["Nimbus Labs"].id
    failures = db.execute(select(PipelineFailure)).scalars().all()
    assert any(f.stage == "source" and f.source == "broken" for f in failures)

    # Second run: everything is known -> no new jobs, analyses come from cache
    calls_before = len(provider.calls)
    run2 = await pipeline.run(db, trigger="test", analyze=True)
    assert run2.stats["new_jobs"] == 0 and run2.stats["duplicates"] == 6
    assert len(provider.calls) == calls_before


async def test_pipeline_survives_ai_outage(db):
    pipeline, _ = build(responder=lambda p, s: AITransientError("down"), sources=[FakeSource([nj("9", "AI Engineer", "Great Co")])])
    run = await pipeline.run(db, trigger="test", analyze=True)
    assert run.status == SearchRunStatus.COMPLETED
    assert run.stats["analysis_failed"] >= 1
    job = db.execute(select(Job).where(Job.company == "Great Co")).scalars().one()
    assert job.pipeline_status == JobPipelineStatus.ANALYSIS_FAILED and "down" in job.analysis_error


async def test_pipeline_without_ai_provider(db):
    settings = Settings(ai_route_job_analysis="gemini", ai_route_classification="openrouter", ai_route_fallback="", gemini_api_key="", openrouter_api_key="", groq_api_key="", job_sources_enabled="fakeboard")
    from app.ai.factory import build_ai_router

    analyzer = JobAnalyzer(build_ai_router(settings), settings)
    pipeline = JobPipeline(SourceRegistry(settings, sources=[FakeSource([nj("7", "Engineer II", "Mystery Co", desc="LLM work")])]), analyzer, settings)
    run = await pipeline.run(db, trigger="test", analyze=True)
    assert run.status == SearchRunStatus.COMPLETED
    assert run.stats.get("analysis_skipped")
    job = db.execute(select(Job).where(Job.company == "Mystery Co")).scalars().one()
    assert job.pipeline_status == JobPipelineStatus.PENDING_ANALYSIS  # unsure jobs wait for a human / AI


async def test_search_endpoint_runs_pipeline(client, db):
    from app.main import app

    pipeline, _ = build(sources=[FakeSource([nj("11", "Backend Engineer", "Great Co")])])
    app.state.pipeline = pipeline
    r = client.post("/api/jobs/search", json={"analyze": True})
    assert r.status_code == 202
    run_id = r.json()["run_id"]
    r = client.get(f"/api/search-runs/{run_id}")
    assert r.status_code == 200 and r.json()["status"] == "COMPLETED"
    assert r.json()["stats"]["new_jobs"] == 1
    assert client.get("/api/jobs", params={"source": "fakeboard"}).json()["total"] == 1


async def test_refilter_endpoint_applies_new_rules(client, db):
    from app.main import app

    pipeline, _ = build(sources=[FakeSource([nj("21", "AI Engineer", "US Only Co", location="USA")])])
    app.state.pipeline = pipeline
    client.patch("/api/settings", json={"filter_rules": {**client.get("/api/settings").json()["filter_rules"], "reject_remote_outside_regions": False}})
    client.post("/api/jobs/search", json={"analyze": False})
    job = client.get("/api/jobs", params={"source": "fakeboard"}).json()["items"][0]
    assert job["pipeline_status"] == "PENDING_ANALYSIS"
    client.patch("/api/settings", json={"filter_rules": {**client.get("/api/settings").json()["filter_rules"], "reject_remote_outside_regions": True}})
    r = client.post("/api/jobs/refilter")
    assert r.status_code == 200 and r.json()["reset"] >= 1
    job = client.get("/api/jobs", params={"source": "fakeboard", "include_rejected": True}).json()["items"][0]
    assert job["pipeline_status"] == "REJECTED_BY_RULES" and "restricted" in job["filter_reason"]
