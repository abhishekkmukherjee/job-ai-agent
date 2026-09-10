"""The discovery pipeline (spec section 1).

    Collect -> Normalize -> Dedupe -> Rule filter -> (cheap AI filter) -> AI analysis
    -> (guarded auto-apply, off by default) -> Notify

Every stage isolates failures per source / per job: one bad posting is recorded in
`pipeline_failures` and the run continues (spec section 19).
"""
from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, time as dtime, timezone
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents.job_analyzer import AnalysisFailed, JobAnalyzer
from ..ai.base import AIUnavailableError
from ..config import Settings
from ..database import session_scope
from ..logging_config import log_event
from ..models import (
    Application,
    ApplicationStatus,
    Job,
    JobPipelineStatus,
    JobUserAction,
    PipelineFailure,
    Profile,
    Recommendation,
    SearchRun,
    SearchRunStatus,
)
from ..schemas.application import ApplicationCreate
from ..schemas.job import NormalizedJob
from ..services import application_service
from ..services.email_apply import EmailApplier, find_application_email
from ..services.location import location_rank
from ..services.profile_service import get_profile
from ..services.settings_service import get_runtime_settings

COVER_EMAIL_QUESTION = (
    "Write a concise cover email (120-170 words, plain text, no subject line, no placeholders) applying for this role. "
    "Open with a greeting, say which role you are applying for, give 2-3 concrete reasons from the profile, and close politely with the candidate's name."
)
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
        preparer: Any | None = None,
        browser_agent: Any | None = None,
        email_applier: Any | None = None,
    ):
        self.registry = registry
        self.analyzer = analyzer
        self.settings = settings
        self.notifier = notifier
        self.preparer = preparer
        self.browser_agent = browser_agent
        self.email_applier = email_applier if email_applier is not None else EmailApplier(settings)
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

    async def _notify_event(self, title: str, lines: list[str], link: str | None = None) -> None:
        if self.notifier is None or not hasattr(self.notifier, "send_event"):
            return
        try:
            await self.notifier.send_event(title, lines, link)
        except Exception as e:  # noqa: BLE001 - notifications never break the run
            log_event("NOTIFICATION_FAILED", error=str(e)[:200], level=logging.WARNING)

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
                    await self._auto_apply(db, run, profile, stats)
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
                await self._notify_event(f"Job Agent run #{run.id} FAILED", [f"{type(e).__name__}: {str(e)[:300]}"])
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
        batch = [(j.id, j.pipeline_status == JobPipelineStatus.ANALYZED) for j in pending[:limit]]
        concurrency = max(1, int(self.settings.ai_analysis_concurrency or 1))
        if concurrency == 1:
            for job in pending[:limit]:
                await self._analyze_one(db, run, job, profile, job.pipeline_status == JobPipelineStatus.ANALYZED, stats)
        else:
            # Several jobs at once: each worker owns its own session; the providers' throttles and
            # cooldowns spread the load across Gemini / Groq / OpenRouter.
            sem = asyncio.Semaphore(concurrency)

            async def worker(job_id: int, was_analyzed: bool) -> None:
                async with sem:
                    with session_scope() as s:
                        job = s.get(Job, job_id)
                        prof = get_profile(s)
                        if job is not None:
                            await self._analyze_one(s, run, job, prof, was_analyzed, stats, failure_db=db)

            await asyncio.gather(*(worker(jid, was) for jid, was in batch))
        if len(pending) > limit:
            stats["analysis_deferred"] = len(pending) - limit

    async def _analyze_one(
        self, db: Session, run: SearchRun, job: Job, profile: Profile, was_analyzed: bool, stats: dict, failure_db: Session | None = None
    ) -> None:
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
            self._record_failure(failure_db or db, run, "analysis", e, job_id=job.id)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            stats["analysis_failed"] += 1
            stats["failures"] += 1
            self._record_failure(failure_db or db, run, "analysis", e, job_id=job.id)

    # ---------------------------------------------------------- auto-apply
    def _start_of_local_day(self) -> datetime:
        try:
            tz = ZoneInfo(self.settings.schedule_timezone)
        except (ZoneInfoNotFoundError, ValueError):
            tz = timezone.utc
        local_now = datetime.now(tz)
        return datetime.combine(local_now.date(), dtime.min, tzinfo=tz).astimezone(timezone.utc)

    @staticmethod
    def _recently_attempted(app: Application, hours: int = 24) -> bool:
        """Skip an application the agent already tried recently; blocked-domain ones are never retried."""
        fr = app.fill_result or {}
        if not fr.get("auto_apply_attempted"):
            return False
        if fr.get("auto_apply") == "blocked_domain":
            return True
        at = fr.get("at")
        if not at:
            return True
        try:
            when = datetime.fromisoformat(str(at))
        except ValueError:
            return True
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - when).total_seconds() < hours * 3600

    def _auto_applied_today(self, db: Session) -> int:
        since = self._start_of_local_day()
        rows = db.execute(select(Application).where(Application.applied_at.isnot(None))).scalars().all()
        count = 0
        for a in rows:
            applied = a.applied_at if a.applied_at.tzinfo else a.applied_at.replace(tzinfo=timezone.utc)
            if applied >= since and (a.fill_result or {}).get("auto_submit"):
                count += 1
        return count

    async def _apply_by_email(
        self, db: Session, run: SearchRun, job: Job, app: Application | None, apply_email: str, cfg: Any, stats: dict,
        form_blockers: list[str] | None = None,
    ) -> bool:
        """Send the tailored resume + a grounded cover email to the address the posting names.  Returns True if sent."""
        url = job.apply_url or job.url or ""
        if self.email_applier.recently_emailed_company(db, job.company, cfg.email_per_company_days):
            if app is None:
                app = application_service.create_application(db, ApplicationCreate(job_id=job.id, status=ApplicationStatus.SHORTLISTED))
            app.fill_result = {**(app.fill_result or {}), "auto_apply_attempted": True, "auto_apply": "company_recently_emailed", "to": apply_email}
            db.commit()
            stats["auto_skipped_same_company"] = stats.get("auto_skipped_same_company", 0) + 1
            return False
        pending: list[str] = []
        try:
            if app is None:
                app = application_service.create_application(db, ApplicationCreate(job_id=job.id, status=ApplicationStatus.APPROVED))
            app = await self.preparer.prepare(db, app)
            if not cfg.allow_needs_review_answers:
                pending = [str(a.get("question")) for a in (app.answers or []) if isinstance(a, dict) and a.get("needs_review")]
            body = None
            if not pending:
                cover = await self.preparer.answerer.answer(db, job, [COVER_EMAIL_QUESTION])
                if cover and cover[0].answer.strip() and not cover[0].needs_review:
                    body = cover[0].answer.strip()
                else:
                    pending = ["cover email could not be written from the profile"]
            if pending:
                app.fill_result = {**(app.fill_result or {}), "auto_apply_attempted": True, "auto_apply": "email_needs_review", "to": apply_email}
                db.commit()
                stats["auto_needs_review"] += 1
                if cfg.notify_each:
                    await self._notify_event(
                        f"Needs you: {job.title} at {job.company}",
                        [f"Match {job.match_score}%", f"Apply by email to {apply_email} - held because:", *[f"- {p}" for p in pending[:4]], "Finish it from the dashboard."],
                        url,
                    )
                return False
            profile = get_profile(db)
            subject = f"Application for {job.title} - {profile.full_name}"
            sent = await asyncio.to_thread(self.email_applier.send, apply_email, subject, body, app.resume_path, profile.email or None)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            stats["failures"] += 1
            self._record_failure(db, run, "auto_apply_email", e, job_id=job.id)
            log_event("APPLICATION_FAILED", job_id=job.id, stage="auto_apply_email", error=str(e)[:300], level=logging.WARNING)
            if cfg.notify_each:
                await self._notify_event(f"Email application failed: {job.title} at {job.company}", [str(e)[:250]], url)
            return False
        app.cover_note = body
        app.fill_result = {**(app.fill_result or {}), **sent, "auto_apply_attempted": True, "auto_submit": True, "submitted": True, "form_blockers": form_blockers or []}
        if app.status in (ApplicationStatus.DISCOVERED, ApplicationStatus.SHORTLISTED):
            application_service.transition_status(db, app, ApplicationStatus.APPROVED, note="auto-apply")
        if app.status in (ApplicationStatus.APPROVED, ApplicationStatus.PREPARING):
            application_service.transition_status(db, app, ApplicationStatus.READY_TO_APPLY, note="email prepared")
        application_service.transition_status(db, app, ApplicationStatus.APPLIED, note=f"applied by email to {apply_email}")
        db.commit()
        stats["auto_applied"] += 1
        stats["auto_emailed"] = stats.get("auto_emailed", 0) + 1
        log_event("AUTO_APPLIED", application_id=app.id, job_id=job.id, company=job.company, title=job.title, channel="email")
        if cfg.notify_each:
            await self._notify_event(
                f"Applied by email: {job.title} at {job.company}",
                [f"Match {job.match_score}%", f"Sent to {apply_email} with {sent.get('attachment', 'resume')} attached.", f"Subject: {subject}"],
                url,
            )
        return True

    async def _auto_apply(self, db: Session, run: SearchRun, profile: Profile, stats: dict) -> None:
        """Submit applications for top matches when every guard passes.

        Guards: score threshold, daily cap, blocked domains (sites that forbid automation),
        no answer flagged for review, and the browser agent's own checks (no CAPTCHA, every
        required field filled, a real submit button, a confirmation after submitting).
        """
        cfg = get_runtime_settings(db).auto_apply
        stats["auto_applied"] = 0
        stats["auto_needs_review"] = 0
        if not cfg.enabled:
            return
        if self.preparer is None or self.browser_agent is None:
            stats["auto_apply_skipped"] = "browser agent not available in this process"
            return
        budget = max(0, cfg.daily_cap - self._auto_applied_today(db))
        stats["auto_apply_budget"] = budget
        if budget <= 0:
            stats["auto_apply_skipped"] = "daily cap reached"
            return
        stmt = (
            select(Job)
            .where(
                Job.pipeline_status == JobPipelineStatus.ANALYZED, Job.match_score >= cfg.min_score,
                Job.user_action != JobUserAction.DISMISSED, Job.duplicate_of_id.is_(None), Job.is_sample.is_(False),
            )
            .order_by(Job.match_score.desc(), Job.discovered_at.desc())
        )
        if cfg.require_recommendation_apply:
            stmt = stmt.where(Job.recommendation == Recommendation.APPLY)
        blocked = [d.lower().strip() for d in cfg.blocked_domains if d.strip()]
        finished = {ApplicationStatus.APPLIED, ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER, ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN}
        candidates = db.execute(stmt).scalars().all()
        # Best score first; among equal scores the candidate's city priority decides (Bangalore > Pune > ... > remote).
        candidates.sort(key=lambda j: (-(j.match_score or 0), location_rank(j, profile)))
        email_ok = cfg.email_enabled and self.email_applier is not None and self.email_applier.is_configured()
        for job in candidates:
            if budget <= 0:
                break
            url = job.apply_url or job.url
            apply_email = find_application_email(job.description or "") if email_ok else None
            if not url and not apply_email:
                continue
            app = application_service.get_application_for_job(db, job.id)
            if app is not None and (app.status in finished or self._recently_attempted(app)):
                continue
            domain = urlparse(url).netloc.lower() if url else ""
            is_blocked = bool(domain) and any(domain == b or domain.endswith("." + b) for b in blocked)
            if apply_email and (is_blocked or not url):
                sent = await self._apply_by_email(db, run, job, app, apply_email, cfg, stats)
                if sent:
                    budget -= 1
                continue
            if is_blocked:
                if app is None:
                    app = application_service.create_application(db, ApplicationCreate(job_id=job.id, status=ApplicationStatus.SHORTLISTED))
                app.fill_result = {**(app.fill_result or {}), "auto_apply_attempted": True, "auto_apply": "blocked_domain", "domain": domain}
                app.notes = ((app.notes or "") + f"\nAuto-apply skipped: {domain} requires a manual application.").strip()
                db.commit()
                stats["auto_needs_review"] += 1
                if cfg.notify_each:
                    await self._notify_event(
                        f"Manual apply needed: {job.title} at {job.company}",
                        [f"Match {job.match_score}%", f"{domain} does not allow automated applications.", "Open the link and use the prepared answers from the dashboard."],
                        url,
                    )
                continue
            pending: list[str] = []
            result = None
            try:
                if app is None:
                    app = application_service.create_application(db, ApplicationCreate(job_id=job.id, status=ApplicationStatus.APPROVED))
                app = await self.preparer.prepare(db, app)
                # Answers flagged for review are never typed into a form (the browser agent skips them);
                # they only block the submission when the form requires that field.
                result = await self.browser_agent.fill_application(db, app, headless=True, submit=True)
            except Exception as e:  # noqa: BLE001
                db.rollback()
                stats["failures"] += 1
                self._record_failure(db, run, "auto_apply", e, job_id=job.id)
                log_event("APPLICATION_FAILED", job_id=job.id, stage="auto_apply", error=str(e)[:300], level=logging.WARNING)
                if cfg.notify_each:
                    await self._notify_event(f"Auto-apply failed: {job.title} at {job.company}", [str(e)[:250]], url)
                continue
            app.fill_result = {**(app.fill_result or {}), "auto_apply_attempted": True}
            db.commit()
            if result is not None and result.submitted:
                budget -= 1
                stats["auto_applied"] += 1
                log_event("AUTO_APPLIED", application_id=app.id, job_id=job.id, company=job.company, title=job.title)
                if cfg.notify_each:
                    await self._notify_event(
                        f"Applied: {job.title} at {job.company}",
                        [
                            f"Match {job.match_score}%",
                            f"Fields filled: {result.fields_filled}, questions answered: {result.questions_answered}, "
                            f"resume: {'uploaded' if result.resume_uploaded else 'not uploaded'}",
                            f"Confirmation: {result.submit_evidence}",
                        ],
                        url,
                    )
            else:
                # The form could not be submitted; if the posting also accepts applications by email, use that.
                if apply_email and not pending:
                    sent = await self._apply_by_email(db, run, job, app, apply_email, cfg, stats, form_blockers=(result.blockers if result else []))
                    if sent:
                        budget -= 1
                        continue
                stats["auto_needs_review"] += 1
                if pending:
                    reasons = [f"answer needs your review: {q}" for q in pending]
                elif result is not None and result.blockers:
                    reasons = list(result.blockers)
                elif result is not None:
                    reasons = [result.message]
                else:
                    reasons = ["form could not be completed"]
                if cfg.notify_each:
                    await self._notify_event(
                        f"Needs you: {job.title} at {job.company}",
                        [f"Match {job.match_score}%", "Prepared but NOT submitted:", *[f"- {b}" for b in reasons[:5]], "Finish it from the dashboard."],
                        url,
                    )
