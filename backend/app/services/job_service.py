"""Job queries used by the API."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from ..models import Application, Job, JobPipelineStatus, JobUserAction, Recommendation, RemoteType
from ..schemas.job import JobListResponse, JobRead, JobSummary


@dataclass
class JobFilters:
    min_score: int | None = None
    max_score: int | None = None
    query: str | None = None          # free text over title/company
    role: str | None = None           # title contains
    location: str | None = None
    remote: RemoteType | None = None
    company: str | None = None
    source: str | None = None
    pipeline_status: JobPipelineStatus | None = None
    recommendation: Recommendation | None = None
    user_action: JobUserAction | None = None
    application_status: str | None = None
    include_dismissed: bool = False
    include_rejected: bool = False
    include_samples: bool = True
    only_analyzed: bool = False
    sort: str = "score"               # score | newest | posted
    page: int = 1
    page_size: int = 25


def _apply_filters(stmt: Select, f: JobFilters) -> Select:
    if f.min_score is not None:
        stmt = stmt.where(Job.match_score >= f.min_score)
    if f.max_score is not None:
        stmt = stmt.where(Job.match_score <= f.max_score)
    if f.query:
        like = f"%{f.query.strip()}%"
        stmt = stmt.where(or_(Job.title.ilike(like), Job.company.ilike(like), Job.description.ilike(like)))
    if f.role:
        stmt = stmt.where(Job.title.ilike(f"%{f.role.strip()}%"))
    if f.location:
        stmt = stmt.where(Job.location.ilike(f"%{f.location.strip()}%"))
    if f.remote is not None:
        stmt = stmt.where(Job.remote_type == f.remote)
    if f.company:
        stmt = stmt.where(Job.company.ilike(f"%{f.company.strip()}%"))
    if f.source:
        stmt = stmt.where(Job.source == f.source.strip().lower())
    if f.pipeline_status is not None:
        stmt = stmt.where(Job.pipeline_status == f.pipeline_status)
    if f.recommendation is not None:
        stmt = stmt.where(Job.recommendation == f.recommendation)
    if f.user_action is not None:
        stmt = stmt.where(Job.user_action == f.user_action)
    elif not f.include_dismissed:
        stmt = stmt.where(Job.user_action != JobUserAction.DISMISSED)
    if not f.include_rejected and f.pipeline_status is None:
        stmt = stmt.where(
            Job.pipeline_status.notin_([JobPipelineStatus.REJECTED_BY_RULES, JobPipelineStatus.REJECTED_BY_AI_FILTER])
        )
    if not f.include_samples:
        stmt = stmt.where(Job.is_sample.is_(False))
    if f.only_analyzed:
        stmt = stmt.where(Job.match_score.isnot(None))
    if f.application_status:
        stmt = stmt.where(Job.application.has(Application.status == f.application_status))
    stmt = stmt.where(Job.duplicate_of_id.is_(None))
    return stmt


def list_jobs(db: Session, f: JobFilters) -> JobListResponse:
    base = _apply_filters(select(Job), f)
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()

    if f.sort == "newest":
        order = [Job.discovered_at.desc(), Job.id.desc()]
    elif f.sort == "posted":
        order = [Job.posted_at.desc().nullslast(), Job.id.desc()]
    else:
        order = [Job.match_score.desc().nullslast(), Job.discovered_at.desc()]
    stmt = base.order_by(*order).offset((f.page - 1) * f.page_size).limit(f.page_size)
    jobs = db.execute(stmt).scalars().all()
    return JobListResponse(items=[job_to_summary(j) for j in jobs], total=total, page=f.page, page_size=f.page_size)


def job_to_summary(job: Job) -> JobSummary:
    summary = JobSummary.model_validate(job)
    desc = (job.description or "").strip()
    summary.description_preview = (desc[:220] + "...") if len(desc) > 220 else desc
    if job.application is not None:
        summary.application_id = job.application.id
        summary.application_status = job.application.status.value
    return summary


def job_to_read(job: Job) -> JobRead:
    data = JobRead.model_validate(job)
    if job.application is not None:
        data.application_id = job.application.id
        data.application_status = job.application.status.value
    return data


def get_job(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


def set_user_action(db: Session, job_id: int, action: JobUserAction) -> Job:
    job = get_job(db, job_id)
    job.user_action = action
    db.commit()
    db.refresh(job)
    return job


def distinct_sources(db: Session) -> list[str]:
    return [r[0] for r in db.execute(select(Job.source).distinct().order_by(Job.source)).all()]


def distinct_companies(db: Session, limit: int = 200) -> list[str]:
    stmt = select(Job.company).where(Job.company != "").distinct().order_by(Job.company).limit(limit)
    return [r[0] for r in db.execute(stmt).all()]
