from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import PipelineFailure, SearchRun
from ..schemas.job import PipelineFailureRead, SearchRunRead
from .deps import get_db

router = APIRouter(prefix="/api", tags=["runs"])


@router.get("/search-runs", response_model=list[SearchRunRead])
def list_runs(limit: int = Query(20, ge=1, le=200), db: Session = Depends(get_db)) -> list[SearchRunRead]:
    rows = db.execute(select(SearchRun).order_by(SearchRun.started_at.desc()).limit(limit)).scalars().all()
    return [SearchRunRead.model_validate(r) for r in rows]


@router.get("/search-runs/{run_id}", response_model=SearchRunRead)
def get_run(run_id: int, db: Session = Depends(get_db)) -> SearchRunRead:
    from fastapi import HTTPException

    row = db.get(SearchRun, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return SearchRunRead.model_validate(row)


@router.get("/failures", response_model=list[PipelineFailureRead])
def list_failures(
    limit: int = Query(50, ge=1, le=500), run_id: int | None = None, db: Session = Depends(get_db)
) -> list[PipelineFailureRead]:
    stmt = select(PipelineFailure).order_by(PipelineFailure.created_at.desc()).limit(limit)
    if run_id is not None:
        stmt = stmt.where(PipelineFailure.run_id == run_id)
    return [PipelineFailureRead.model_validate(r) for r in db.execute(stmt).scalars().all()]
