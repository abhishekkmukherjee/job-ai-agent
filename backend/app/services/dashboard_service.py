"""Aggregations for the dashboard endpoint."""
from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Application, ApplicationStatus, Job, JobPipelineStatus, JobUserAction, Recommendation, SearchRun
from ..schemas.dashboard import DashboardCounts, DashboardResponse
from .job_service import job_to_summary

STRONG_MATCH_THRESHOLD = 75


def _start_of_today(tz_name: str | None = None) -> datetime:
    """Midnight of the user's local day (SCHEDULE_TIMEZONE), expressed in UTC."""
    tz = timezone.utc
    if tz_name:
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            tz = timezone.utc
    local_now = datetime.now(tz)
    return datetime.combine(local_now.date(), time.min, tzinfo=tz).astimezone(timezone.utc)


def build_dashboard(db: Session, ai_status: dict | None = None, sources: list[dict] | None = None) -> DashboardResponse:
    today = _start_of_today(get_settings().schedule_timezone)
    visible = (Job.user_action != JobUserAction.DISMISSED) & (Job.duplicate_of_id.is_(None))

    def count(stmt):
        return db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    submitted_statuses = [
        ApplicationStatus.APPLIED, ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER, ApplicationStatus.REJECTED,
    ]
    counts = DashboardCounts(
        jobs_discovered=count(select(Job.id).where(visible)),
        jobs_discovered_today=count(select(Job.id).where(visible, Job.discovered_at >= today)),
        strong_matches=count(select(Job.id).where(visible, Job.match_score >= STRONG_MATCH_THRESHOLD)),
        strong_matches_today=count(
            select(Job.id).where(visible, Job.match_score >= STRONG_MATCH_THRESHOLD, Job.discovered_at >= today)
        ),
        recommended_applications=count(select(Job.id).where(visible, Job.recommendation == Recommendation.APPLY)),
        applications_submitted=count(select(Application.id).where(Application.status.in_(submitted_statuses))),
        interviews=count(select(Application.id).where(Application.status == ApplicationStatus.INTERVIEW)),
        pending_review=count(select(Job.id).where(visible, Job.recommendation == Recommendation.REVIEW)),
        ready_to_apply=count(select(Application.id).where(Application.status == ApplicationStatus.READY_TO_APPLY)),
    )

    top_jobs_stmt = (
        select(Job)
        .where(visible, Job.pipeline_status == JobPipelineStatus.ANALYZED, Job.match_score.isnot(None))
        .order_by(Job.match_score.desc(), Job.discovered_at.desc())
        .limit(8)
    )
    top_jobs = [job_to_summary(j).model_dump(mode="json") for j in db.execute(top_jobs_stmt).scalars().all()]

    recent_apps_stmt = select(Application).order_by(Application.updated_at.desc()).limit(6)
    recent_applications = [
        {
            "id": a.id,
            "job_id": a.job_id,
            "company": a.company,
            "role": a.role,
            "status": a.status.value,
            "match_score": a.match_score,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None,
        }
        for a in db.execute(recent_apps_stmt).scalars().all()
    ]

    last_run_row = db.execute(select(SearchRun).order_by(SearchRun.started_at.desc()).limit(1)).scalars().first()
    last_run = None
    if last_run_row is not None:
        last_run = {
            "id": last_run_row.id,
            "status": last_run_row.status.value,
            "trigger": last_run_row.trigger,
            "started_at": last_run_row.started_at.isoformat() if last_run_row.started_at else None,
            "finished_at": last_run_row.finished_at.isoformat() if last_run_row.finished_at else None,
            "stats": last_run_row.stats or {},
            "error": last_run_row.error,
        }

    return DashboardResponse(
        counts=counts,
        top_jobs=top_jobs,
        recent_applications=recent_applications,
        last_run=last_run,
        ai=ai_status or {},
        sources=sources or [],
    )
