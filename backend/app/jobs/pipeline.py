"""The discovery pipeline (spec section 1).

    Collect -> Normalize -> Dedupe -> Rule filter -> (cheap AI filter) -> AI analysis -> Notify

Every stage isolates failures per source / per job: one bad posting is recorded in
`pipeline_failures` and the run continues (spec section 19).
"""
from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents.job_analyzer import AnalysisFailed, JobAnalyzer
from ..ai.base import AIUnavailableError
from ..config import Settings
from ..database import session_scope
from ..logging_config import log_event
from ..models import Job, JobPipelineStatus, JobUserAction, PipelineFailure, Profile, SearchRun, SearchRunStatus
from ..schemas.job import NormalizedJob
from ..services.profile_service import get_profile
from ..services.settings_service import get_runtime_settings
from .dedupe import content_hash, find_duplicate
from .filters import FilterOutcome, RuleFilter
from .sources.base import SourceError
from .sources.registry import SourceRegistry


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobPipeline:
    def __init__(
        self,
        registry: SourceRegistry,
        analyzer: JobAnalyzer | None,
        settings: Settings,
        notifier: Any | None = None,
    ):
        self.registry = registry
        self.analyzer = analyzer
        self.settings = settings
        self.notifier = notifier
        self.is_running = False
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ run mgmt
    def create_run(self, db: Session, trigger: str = "manual", sources: list[str] | None = None) -> SearchRun:
        run = SearchRun(trigger=trigger, status=SearchRunStatus.RUNNING, sources=sources or [], stats={})
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    async def run_in_background(
        self,
        run_id: int,
        sources: list[str] | None = None,
        analyze: bool = True,
        notify: bool = False,
        max_per_source: int | None = None,
    ) -> None:
        """Entry point for FastAPI BackgroundTasks / scheduler - owns its own session."""
        with session_scope() as db:
            run = db.get(SearchRun, run_id)
            await self.run(db, run=run, sources=sources, analyze=analyze, notify=notify, max_per_source=max_per_source)

    def _record_failure(self, db: Session, run: SearchRun, stage: str, error: Exception | str, **extra: Any) -> None:
        msg = f"{type(error).__name__}: {error}" if isinstance(error, Exception) else str(error)
        db.add(
            PipelineFailure(
                run_id=run.id, stage=stage, source=extra.get("source", ""), job_id=extra.get("job_id"),
                external_id=extra.get("external_id", ""), error=msg[:2000], payload=extra.get("payload"),
            )
        )
        db.commit()

    # ---------------------------------------------------------------- main
    async def run(
        self,
        db: Session,
        run: SearchRun | None = None,
        trigger: str = "manual",
        sources: list[str] | None = None,
        analyze: bool = True,
        notify: bool = False,
        max_per_source: int | None = None,
    ) -> SearchRun:
        if run is None:
            run = self.create_run(db, trigger=trigger, sources=sources)
        async with self._lock:
            self.is_running = True
            stats: dict[str, Any] = {
                "sources": {}, "fetched": 0, "new_jobs": 0, "duplicates": 0, "invalid": 0,
                "filtered_out": 0, "passed_filter": 0, "ai_filtered_out": 0, "analyzed": 0,
                "analysis_failed": 0, "cache_hits": 0, "strong_matches": 0, "failures": 0, "notified": False,
            }
            log_event("SEARCH_RUN_STARTED", run_id=run.id, trigger=run.trigger)
            try:
                profile = get_profile(db)
                await self._collect(db, run, profile, sources, max_per_source, stats)
                await self._filter(db, run, profile, stats)
                if analyze:
                    await self._analyze(db, run, profile, stats)
                if notify and self.notifier is not None:
                    try:
                        await self.notifier.send_daily_report(db, run, stats)
                        stats["notified"] = True
                    except Exception as e:  # noqa: BLE001
                        stats["failures"] += 1
                        self._record_failure(db, run, "notify", e)
                run.status = SearchRunStatus.COMPLETED
            except Exception as e:  # noqa: BLE001 - a run must never crash the server
                run.status = SearchRunStatus.FAILED
                run.error = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-1500:]}"
                log_event("SEARCH_RUN_COMPLETED", run_id=run.id, status="FAILED", error=str(e), level=logging.ERROR)
            finally:
                run.finished_at = utcnow()
                run.stats = stats
                db.add(run)
                db.commit()
                self.is_running = False
            if run.status == SearchRunStatus.COMPLETED:
                log_event("SEARCH_RUN_COMPLETED", run_id=run.id, status="COMPLETED", **{k: v for k, v in stats.items() if k != "sources"})
            return run

    # ------------------------------------------------------------- collect
    async def _collect(
        self, db: Session, run: SearchRun, profile: Profile, sources: list[str] | None, max_per_source: int | None, stats: dict
    ) -> None:
        ctx = self.registry.build_context(db, profile, max_results=max_per_source)
        enabled = self.registry.enabled_names(db)
        wanted = [s for s in (sources or enabled) if s in self.registry.sources]
        run.sources = wanted
        for name in wanted:
            source = self.registry.sources[name]
            entry: dict[str, Any] = {"fetched": 0, "new": 0, "duplicates": 0, "error": ""}
            stats["sources"][name] = entry
            if not source.is_configured(ctx):
                entry["error"] = f"not configured ({source.requires or 'unsupported'})"
                continue
            try:
                jobs = await source.fetch(ctx)
            except (SourceError, Exception) as e:  # noqa: BLE001
                entry["error"] = str(e)[:300]
                stats["failures"] += 1
                self._record_failure(db, run, "source", e, source=name)
                log_event("SOURCE_FAILED", source=name, error=str(e)[:200], level=logging.WARNING)
                continue
            entry["fetched"] = len(jobs)
            stats["fetched"] += len(jobs)
            log_event("SOURCE_FETCHED", source=name, count=len(jobs))
            for nj in jobs:
                try:
                    created = self._store(db, nj)
                except Exception as e:  # noqa: BLE001
                    db.rollback()
                    stats["invalid"] += 1
                    stats["failures"] += 1
                    self._record_failure(db, run, "normalize", e, source=name, external_id=str(getattr(nj, "external_id", "")))
                    continue
                if created:
                    entry["new"] += 1
                    stats["new_jobs"] += 1
                else:
                    entry["duplicates"] += 1
                    stats["duplicates"] += 1

    def _store(self, db: Session, nj: NormalizedJob) -> bool:
        """Insert a normalized job unless it duplicates an existing one.  Returns True if created."""
        dup = find_duplicate(db, source=nj.source, external_id=nj.external_id, title=nj.title, company=nj.company, url=nj.url)
        if dup is not None:
            if dup.source == nj.source and dup.external_id == nj.external_id:
                return False  # already known from this source
            # Same posting from another board: keep a lightweight record pointing at the original.
            if not db.execute(select(Job.id).where(Job.source == nj.source, Job.external_id == nj.external_id)).first():
                db.add(
                    Job(
                        external_id=nj.external_id, source=nj.source, title=nj.title, company=nj.company,
                        location=nj.location, remote_type=nj.remote_type, url=nj.url, apply_url=nj.apply_url,
                        content_hash=content_hash(nj.title, nj.company), duplicate_of_id=dup.id,
                        pipeline_status=JobPipelineStatus.REJECTED_BY_RULES, filter_reason=f"duplicate of job {dup.id} ({dup.source})",
                        description="", posted_at=nj.posted_at,
                    )
                )
                db.commit()
            log_event("JOB_DUPLICATE", source=nj.source, external_id=nj.external_id, duplicate_of=dup.id)
            return False
        job = Job(
            external_id=nj.external_id, source=nj.source, title=nj.title.strip()[:300], company=(nj.company or "").strip()[:300],
            location=(nj.location or "").strip()[:300], remote_type=nj.remote_type, salary_min=nj.salary_min,
            salary_max=nj.salary_max, salary_currency=nj.salary_currency or "", description=nj.description or "",
            url=nj.url or "", apply_url=nj.apply_url or nj.url or "", tags=nj.tags[:30], posted_at=nj.posted_at,
            content_hash=content_hash(nj.title, nj.company), pipeline_status=JobPipelineStatus.NEW, raw=nj.raw,
        )
        db.add(job)
        db.commit()
        log_event("JOB_DISCOVERED", job_id=job.id, source=job.source, title=job.title, company=job.company)
        return True

    async def refilter(self, db: Session) -> dict[str, Any]:
        """Re-run the rule filter on every job that has not been analyzed yet (after rules change)."""
        run = self.create_run(db, trigger="refilter")
        stats: dict[str, Any] = {"reset": 0, "filtered_out": 0, "passed_filter": 0, "ai_filtered_out": 0, "failures": 0}
        jobs = db.execute(
            select(Job).where(
                Job.pipeline_status.in_([
                    JobPipelineStatus.NEW, JobPipelineStatus.PENDING_ANALYSIS,
                    JobPipelineStatus.REJECTED_BY_RULES, JobPipelineStatus.REJECTED_BY_AI_FILTER,
                ]),
                Job.duplicate_of_id.is_(None),
            )
        ).scalars().all()
        for job in jobs:
            job.pipeline_status = JobPipelineStatus.NEW
            job.filter_reason = ""
            stats["reset"] += 1
        db.commit()
        profile = get_profile(db)
        await self._filter(db, run, profile, stats)
        run.status = SearchRunStatus.COMPLETED
        run.finished_at = utcnow()
        run.stats = stats
        db.commit()
        return stats

    # -------------------------------------------------------------- filter
    async def _filter(self, db: Session, run: SearchRun, profile: Profile, stats: dict) -> None:
        rules = get_runtime_settings(db).filter_rules
        rule_filter = RuleFilter(rules)
        new_jobs = db.execute(
            select(Job).where(Job.pipeline_status == JobPipelineStatus.NEW, Job.duplicate_of_id.is_(None))
        ).scalars().all()
        ai_filter_ok = (
            self.settings.ai_quick_filter_enabled and self.analyzer is not None and self.analyzer.ai.is_available()
        )
        for job in new_jobs:
            try:
                result = rule_filter.evaluate(job, profile)
                job.filter_details = {**result.details, "outcome": result.outcome.value}
                if result.outcome == FilterOutcome.REJECT:
                    job.pipeline_status = JobPipelineStatus.REJECTED_BY_RULES
                    job.filter_reason = result.reason
                    stats["filtered_out"] += 1
                    log_event("JOB_FILTERED", job_id=job.id, title=job.title, reason=result.reason)
                elif result.outcome == FilterOutcome.PASS:
                    job.pipeline_status = JobPipelineStatus.PENDING_ANALYSIS
                    job.filter_reason = result.reason
                    stats["passed_filter"] += 1
                    log_event("JOB_PASSED_FILTER", job_id=job.id, title=job.title, reason=result.reason)
                else:  # UNSURE
                    if ai_filter_ok:
                        verdict = await self.analyzer.quick_filter(db, job, profile)
                        job.filter_details["ai_filter"] = verdict.model_dump()
                        if verdict.relevant:
                            job.pipeline_status = JobPipelineStatus.PENDING_ANALYSIS
                            job.filter_reason = f"AI filter: {verdict.reason}"[:500]
                            stats["passed_filter"] += 1
                            log_event("JOB_PASSED_FILTER", job_id=job.id, title=job.title, reason=job.filter_reason)
                        else:
                            job.pipeline_status = JobPipelineStatus.REJECTED_BY_AI_FILTER
                            job.filter_reason = f"AI filter: {verdict.reason}"[:500]
                            stats["ai_filtered_out"] += 1
                            log_event("JOB_FILTERED", job_id=job.id, title=job.title, reason=job.filter_reason)
                    else:
                        job.pipeline_status = JobPipelineStatus.PENDING_ANALYSIS
                        job.filter_reason = f"unsure ({result.reason}); no AI filter available"[:500]
                        stats["passed_filter"] += 1
                db.commit()
            except AIUnavailableError as e:
                db.rollback()
                job.pipeline_status = JobPipelineStatus.PENDING_ANALYSIS
                job.filter_reason = "unsure; AI filter unavailable"
                db.commit()
                stats["passed_filter"] += 1
                self._record_failure(db, run, "filter", e, job_id=job.id)
            except Exception as e:  # noqa: BLE001
                db.rollback()
                stats["failures"] += 1
                self._record_failure(db, run, "filter", e, job_id=job.id)

    # ------------------------------------------------------------- analyze
    async def _analyze(self, db: Session, run: SearchRun, profile: Profile, stats: dict) -> None:
        if self.analyzer is None or not self.analyzer.ai.is_available():
            stats["analysis_skipped"] = "no AI provider configured"
            return
        pending = db.execute(
            select(Job)
            .where(
                Job.pipeline_status.in_([JobPipelineStatus.PENDING_ANALYSIS, JobPipelineStatus.ANALYSIS_FAILED]),
                Job.duplicate_of_id.is_(None),
                Job.user_action != JobUserAction.DISMISSED,
            )
            .order_by(Job.discovered_at.desc())
        ).scalars().all()
        # Jobs with prioritized keywords first, then newest
        pending.sort(key=lambda j: (-len((j.filter_details or {}).get("priority_hits") or []), -(j.discovered_at.timestamp() if j.discovered_at else 0)))
        # Already-scored jobs whose analysis predates the current profile version are re-scored, best first.
        stale = [
            j for j in db.execute(
                select(Job).where(Job.pipeline_status == JobPipelineStatus.ANALYZED, Job.duplicate_of_id.is_(None), Job.user_action != JobUserAction.DISMISSED)
            ).scalars().all()
            if (j.analysis or {}).get("profile_version") != profile.version
        ]
        stale.sort(key=lambda j: -(j.match_score or 0))
        stats["stale_rescored"] = 0
        pending = [*pending, *stale]
        limit = self.settings.ai_max_analyses_per_run
        for job in pending[:limit]:
            was_analyzed = job.pipeline_status == JobPipelineStatus.ANALYZED
            try:
                before = self.analyzer.ai.stats["requests"]
                analysis = await self.analyzer.analyze_job(db, job, profile=profile)
                stats["analyzed"] += 1
                if was_analyzed:
                    stats["stale_rescored"] += 1
                if self.analyzer.ai.stats["requests"] == before:
                    stats["cache_hits"] += 1
                if analysis.match_score >= self.settings.ai_min_score_for_report:
                    stats["strong_matches"] += 1
            except AnalysisFailed as e:
                stats["analysis_failed"] += 1
                stats["failures"] += 1
                self._record_failure(db, run, "analysis", e, job_id=job.id)
            except Exception as e:  # noqa: BLE001
                db.rollback()
                stats["analysis_failed"] += 1
                stats["failures"] += 1
                self._record_failure(db, run, "analysis", e, job_id=job.id)
        if len(pending) > limit:
            stats["analysis_deferred"] = len(pending) - limit
