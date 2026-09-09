from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..schemas.dashboard import DashboardResponse
from ..services import dashboard_service
from .deps import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardResponse)
def read_dashboard(request: Request, db: Session = Depends(get_db)) -> DashboardResponse:
    ai_status = {}
    sources = []
    ai_router = getattr(request.app.state, "ai_router", None)
    if ai_router is not None:
        ai_status = ai_router.status_summary()
    registry = getattr(request.app.state, "source_registry", None)
    if registry is not None:
        sources = registry.describe(db)
    return dashboard_service.build_dashboard(db, ai_status=ai_status, sources=sources)
