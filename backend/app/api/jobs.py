from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..models import JobPipelineStatus, JobUserAction, Recommendation, RemoteType
from ..schemas.job import JobListResponse, JobRead, JobSearchRequest, JobSearchResponse, JobUpdate
from ..services import job_service
from ..services.job_service import JobFilters
from .deps import get_db

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def job_filters(
    min_score: int | None = Query(None, ge=0, le=100),
    max_score: int | None = Query(None, ge=0, le=100),
    q: str | None = None,
    role: str | None = None,
    location: str | None = None,
    remote: RemoteType | None = None,
    company: str | None = None,
    source: str | None = None,
    pipeline_status: JobPipelineStatus | None = None,
    recommendation: Recommendation | None = None,
    user_action: JobUserAction | None = None,
    application_status: str | None = None,
    include_dismissed: bool = False,
    include_rejected: bool = False,
    include_samples: bool = True,
    only_analyzed: bool = False,
    sort: str = Query("score", pattern="^(score|newest|posted)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
) -> JobFilters:
    return JobFilters(
        min_score=min_score, max_score=max_score, query=q, role=role, location=location, remote=remote,
        company=company, source=source, pipeline_status=pipeline_status, recommendation=recommendation,
        user_action=user_action, application_status=application_status, include_dismissed=include_dismissed,
        include_rejected=include_rejected, include_samples=include_samples, only_analyzed=only_analyzed,
        sort=sort, page=page, page_size=page_size,
    )


@router.get("", response_model=JobListResponse)
def list_jobs(filters: JobFilters = Depends(job_filters), db: Session = Depends(get_db)) -> JobListResponse:
    return job_service.list_jobs(db, filters)


@router.get("/meta")
def jobs_meta(db: Session = Depends(get_db)) -> dict:
    return {
        "sources": job_service.distinct_sources(db),
        "companies": job_service.distinct_companies(db),
        "pipeline_statuses": [s.value for s in JobPipelineStatus],
        "recommendations": [r.value for r in Recommendation],
        "remote_types": [r.value for r in RemoteType],
    }


@router.post("/search", response_model=JobSearchResponse, status_code=202)
async def trigger_search(
    body: JobSearchRequest, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)
) -> JobSearchResponse:
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Job pipeline is not initialised")
    if pipeline.is_running:
        raise HTTPException(status_code=409, detail="A search is already running")
    run = pipeline.create_run(db, trigger="manual", sources=body.sources)
    background.add_task(
        pipeline.run_in_background,
        run_id=run.id,
        sources=body.sources,
        analyze=body.analyze,
        notify=body.notify,
        max_per_source=body.max_per_source,
    )
    return JobSearchResponse(run_id=run.id, status="started", message="Job search started in the background")


@router.post("/refilter")
async def refilter_jobs(request: Request, db: Session = Depends(get_db)) -> dict:
    """Re-apply the rule filter to all not-yet-analyzed jobs (use after changing filter rules)."""
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(status_code=503, detail="Job pipeline is not initialised")
    if pipeline.is_running:
        raise HTTPException(status_code=409, detail="A search is already running")
    return await pipeline.refilter(db)


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: int, db: Session = Depends(get_db)) -> JobRead:
    return job_service.job_to_read(job_service.get_job(db, job_id))


@router.patch("/{job_id}", response_model=JobRead)
def patch_job(job_id: int, data: JobUpdate, db: Session = Depends(get_db)) -> JobRead:
    job = job_service.get_job(db, job_id)
    if data.user_action is not None:
        job = job_service.set_user_action(db, job_id, data.user_action)
    return job_service.job_to_read(job)


@router.post("/{job_id}/analyze", response_model=JobRead)
async def analyze_job(job_id: int, request: Request, force: bool = False, db: Session = Depends(get_db)) -> JobRead:
    analyzer = getattr(request.app.state, "job_analyzer", None)
    if analyzer is None:
        raise HTTPException(status_code=503, detail="AI analyzer is not initialised")
    from ..agents.job_analyzer import AnalysisFailed

    job = job_service.get_job(db, job_id)
    try:
        await analyzer.analyze_job(db, job, force=force)
    except AnalysisFailed as e:
        raise HTTPException(status_code=502, detail=f"AI analysis failed: {e}") from e
    db.refresh(job)
    return job_service.job_to_read(job)


@router.post("/{job_id}/tailor-resume")
async def tailor_resume(job_id: int, request: Request, force: bool = False, db: Session = Depends(get_db)) -> dict:
    tailor = getattr(request.app.state, "resume_tailor", None)
    if tailor is None:
        raise HTTPException(status_code=503, detail="Resume tailor is not initialised")
    from ..agents.resume_tailor import TailoringFailed

    job = job_service.get_job(db, job_id)
    try:
        application, resume = await tailor.tailor_for_job(db, job, force=force)
    except TailoringFailed as e:
        raise HTTPException(status_code=502, detail=f"Resume tailoring failed: {e}") from e
    return {"application_id": application.id, "resume": resume.model_dump(), "resume_path": application.resume_path}
