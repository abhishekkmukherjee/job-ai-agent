"""Application tracker service: creation, status transitions, updates."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..logging_config import log_event
from ..models import Application, ApplicationStatus, Job, can_transition
from ..schemas.application import ApplicationCreate, ApplicationListResponse, ApplicationRead, ApplicationUpdate


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class InvalidTransition(HTTPException):
    def __init__(self, current: ApplicationStatus, new: ApplicationStatus):
        super().__init__(status_code=409, detail=f"Cannot move application from {current.value} to {new.value}")


def application_to_read(app: Application) -> ApplicationRead:
    data = ApplicationRead.model_validate(app)
    if app.job is not None and app.job.recommendation is not None:
        data.recommendation = app.job.recommendation.value
    data.has_resume_pdf = bool(app.resume_path) and Path(app.resume_path).exists()
    return data


def get_application(db: Session, app_id: int) -> Application:
    app = db.get(Application, app_id)
    if app is None:
        raise HTTPException(status_code=404, detail=f"Application {app_id} not found")
    return app


def get_application_for_job(db: Session, job_id: int) -> Application | None:
    return db.execute(select(Application).where(Application.job_id == job_id)).scalars().first()


def create_application(db: Session, data: ApplicationCreate) -> Application:
    job = db.get(Job, data.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {data.job_id} not found")
    existing = get_application_for_job(db, job.id)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"An application for this job already exists (id={existing.id}, status={existing.status.value})",
        )
    # Prevent applying twice to the same company for the same role (duplicate postings across sources)
    dup = db.execute(
        select(Application)
        .where(func.lower(Application.company) == (job.company or "").lower())
        .where(func.lower(Application.role) == (job.title or "").lower())
        .where(Application.status.in_([ApplicationStatus.APPLIED, ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER]))
    ).scalars().first()
    if dup is not None:
        raise HTTPException(
            status_code=409,
            detail=f"You already applied to {job.title} at {job.company} (application id={dup.id}).",
        )
    app = Application(
        job_id=job.id,
        company=job.company,
        role=job.title,
        job_url=job.apply_url or job.url,
        source=job.source,
        match_score=job.match_score,
        status=data.status,
        notes=data.notes,
        status_history=[{"status": data.status.value, "at": utcnow().isoformat(), "note": "created"}],
    )
    db.add(app)
    db.commit()
    db.refresh(app)
    log_event("APPLICATION_STARTED", application_id=app.id, job_id=job.id, company=job.company, role=job.title)
    return app


def transition_status(db: Session, app: Application, new_status: ApplicationStatus, note: str = "") -> Application:
    if not can_transition(app.status, new_status):
        raise InvalidTransition(app.status, new_status)
    if app.status != new_status:
        history = list(app.status_history or [])
        history.append({"status": new_status.value, "at": utcnow().isoformat(), "note": note})
        app.status_history = history
        app.status = new_status
        if new_status == ApplicationStatus.APPLIED and app.applied_at is None:
            app.applied_at = utcnow()
    db.add(app)
    return app


def update_application(db: Session, app_id: int, data: ApplicationUpdate) -> Application:
    app = get_application(db, app_id)
    changes = data.model_dump(exclude_unset=True)
    new_status = changes.pop("status", None)
    if new_status is not None:
        transition_status(db, app, ApplicationStatus(new_status), note="manual update")
    for key, value in changes.items():
        setattr(app, key, value)
    db.commit()
    db.refresh(app)
    return app


def list_applications(db: Session, status: ApplicationStatus | None = None, query: str | None = None) -> ApplicationListResponse:
    stmt = select(Application)
    if status is not None:
        stmt = stmt.where(Application.status == status)
    if query:
        like = f"%{query.strip()}%"
        stmt = stmt.where((Application.company.ilike(like)) | (Application.role.ilike(like)))
    stmt = stmt.order_by(Application.updated_at.desc())
    apps = db.execute(stmt).scalars().all()
    return ApplicationListResponse(items=[application_to_read(a) for a in apps], total=len(apps))


def delete_application(db: Session, app_id: int) -> None:
    app = get_application(db, app_id)
    if app.status in {ApplicationStatus.APPLIED, ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER}:
        raise HTTPException(status_code=409, detail="Cannot delete a submitted application; withdraw it instead.")
    db.delete(app)
    db.commit()
