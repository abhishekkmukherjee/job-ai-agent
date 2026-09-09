"""Structured job evaluation against the profile (spec section 7) with caching."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ..ai.base import AIUnavailableError
from ..ai.cache import AIResultCache, job_hash_for
from ..ai.prompts import load_prompt, render_prompt
from ..ai.router import AIRouter
from ..config import Settings
from ..logging_config import log_event
from ..models import Job, JobPipelineStatus, Profile
from ..schemas.ai import JobAnalysis, QuickFilterResult
from ..services.profile_service import get_profile, profile_to_prompt_text

SYSTEM_PROMPT = "You are a precise assistant. You always answer with a single valid JSON object that matches the requested schema exactly."
TASK_ANALYSIS = "job_analysis"
TASK_QUICK_FILTER = "quick_filter"


class AnalysisFailed(Exception):
    """Raised when every provider failed; the failure is already recorded on the job."""


def job_to_prompt_text(job: Job, max_description_chars: int = 7000) -> str:
    desc = (job.description or "").strip()
    if len(desc) > max_description_chars:
        desc = desc[:max_description_chars] + "\n[...description truncated...]"
    lines = [
        f"Title: {job.title}",
        f"Company: {job.company or 'unknown'}",
        f"Location: {job.location or 'not specified'}",
        f"Work mode: {job.remote_type.value if job.remote_type else 'unknown'}",
    ]
    if job.salary_min or job.salary_max:
        lines.append(f"Salary: {job.salary_min or '?'} - {job.salary_max or '?'} {job.salary_currency}")
    if job.posted_at:
        lines.append(f"Posted: {job.posted_at.date().isoformat()}")
    if job.tags:
        lines.append(f"Tags: {', '.join(str(t) for t in job.tags[:20])}")
    lines.append(f"Source: {job.source}")
    lines.append("")
    lines.append("Description:")
    lines.append(desc or "(no description provided)")
    return "\n".join(lines)


class JobAnalyzer:
    def __init__(self, ai_router: AIRouter, settings: Settings, cache: AIResultCache | None = None):
        self.ai = ai_router
        self.settings = settings
        self.cache = cache or AIResultCache()

    # ------------------------------------------------------------ analysis
    def apply_analysis(self, job: Job, analysis: JobAnalysis, model: str, provider: str) -> None:
        analysis.enforce_recommendation_bands()
        job.match_score = analysis.match_score
        job.recommendation = analysis.recommendation
        job.analysis = analysis.model_dump(mode="json")
        job.analyzed_at = datetime.now(timezone.utc)
        job.analysis_model = f"{provider}:{model}" if model else provider
        job.analysis_error = ""
        job.pipeline_status = JobPipelineStatus.ANALYZED

    async def analyze_job(self, db: Session, job: Job, force: bool = False, profile: Profile | None = None) -> JobAnalysis:
        profile = profile or get_profile(db)
        job_hash = job_hash_for(job)
        prompt_version = self.settings.job_analysis_prompt_version
        if not force:
            cached = self.cache.get(db, TASK_ANALYSIS, job_hash, profile.version, prompt_version)
            if cached is not None:
                analysis = JobAnalysis.model_validate(cached.result)
                self.apply_analysis(job, analysis, cached.model, cached.provider)
                db.commit()
                log_event("AI_CACHE_HIT", task=TASK_ANALYSIS, job_id=job.id)
                return analysis

        log_event("AI_ANALYSIS_STARTED", job_id=job.id, title=job.title, company=job.company)
        prompt = render_prompt(
            load_prompt("job_analysis", prompt_version),
            profile=profile_to_prompt_text(profile),
            job=job_to_prompt_text(job),
        )
        try:
            analysis, meta = await self.ai.complete_json(
                TASK_ANALYSIS, prompt, JobAnalysis, system=SYSTEM_PROMPT, temperature=0.1, max_tokens=2048
            )
        except AIUnavailableError as e:
            job.pipeline_status = JobPipelineStatus.ANALYSIS_FAILED
            job.analysis_error = str(e)[:500]
            db.commit()
            log_event("AI_ANALYSIS_FAILED", job_id=job.id, error=str(e)[:300], level=logging.WARNING)
            raise AnalysisFailed(str(e)) from e

        self.apply_analysis(job, analysis, meta.model, meta.provider)
        self.cache.put(
            db, task=TASK_ANALYSIS, job_hash=job_hash, profile_version=profile.version, prompt_version=prompt_version,
            model=meta.model, provider=meta.provider, result=analysis.model_dump(mode="json"), usage=meta.usage,
        )
        db.commit()
        log_event(
            "AI_ANALYSIS_COMPLETED", job_id=job.id, score=analysis.match_score,
            recommendation=analysis.recommendation.value, model=meta.model, provider=meta.provider,
        )
        return analysis

    # -------------------------------------------------------- quick filter
    async def quick_filter(self, db: Session, job: Job, profile: Profile | None = None) -> QuickFilterResult:
        """Cheap relevance check (classification route) for titles the rules could not decide."""
        profile = profile or get_profile(db)
        job_hash = job_hash_for(job)
        prompt_version = self.settings.job_filtering_prompt_version
        cached = self.cache.get(db, TASK_QUICK_FILTER, job_hash, profile.version, prompt_version)
        if cached is not None:
            log_event("AI_CACHE_HIT", task=TASK_QUICK_FILTER, job_id=job.id)
            return QuickFilterResult.model_validate(cached.result)
        prompt = render_prompt(
            load_prompt("job_filtering", prompt_version),
            target_roles=", ".join(profile.target_roles or []),
            years_of_experience=profile.years_of_experience,
            skills=", ".join((profile.skills or [])[:25]),
            title=job.title,
            company=job.company,
            location=job.location,
            description=(job.description or "")[:2500],
        )
        result, meta = await self.ai.complete_json(
            "classification", prompt, QuickFilterResult, system=SYSTEM_PROMPT, temperature=0.0, max_tokens=256
        )
        self.cache.put(
            db, task=TASK_QUICK_FILTER, job_hash=job_hash, profile_version=profile.version, prompt_version=prompt_version,
            model=meta.model, provider=meta.provider, result=result.model_dump(mode="json"), usage=meta.usage,
        )
        db.commit()
        return result
