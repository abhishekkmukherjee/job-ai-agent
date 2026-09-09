from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..models import ApplicationStatus
from ..schemas.application import (
    AnswerQuestionsRequest,
    ApplicationCreate,
    ApplicationListResponse,
    ApplicationRead,
    ApplicationUpdate,
    FillRequest,
    FillResponse,
    PrepareRequest,
)
from ..services import application_service
from .deps import get_db

router = APIRouter(prefix="/api/applications", tags=["applications"])


@router.get("", response_model=ApplicationListResponse)
def list_applications(
    status: ApplicationStatus | None = None, q: str | None = None, db: Session = Depends(get_db)
) -> ApplicationListResponse:
    return application_service.list_applications(db, status=status, query=q)


@router.post("", response_model=ApplicationRead, status_code=201)
def create_application(data: ApplicationCreate, db: Session = Depends(get_db)) -> ApplicationRead:
    app = application_service.create_application(db, data)
    return application_service.application_to_read(app)


@router.get("/statuses")
def statuses() -> dict:
    from ..models.enums import APPLICATION_TRANSITIONS

    return {
        "statuses": [s.value for s in ApplicationStatus],
        "transitions": {k.value: sorted(v.value for v in vals) for k, vals in APPLICATION_TRANSITIONS.items()},
    }


@router.get("/{app_id}", response_model=ApplicationRead)
def get_application(app_id: int, db: Session = Depends(get_db)) -> ApplicationRead:
    return application_service.application_to_read(application_service.get_application(db, app_id))


@router.patch("/{app_id}", response_model=ApplicationRead)
def patch_application(app_id: int, data: ApplicationUpdate, db: Session = Depends(get_db)) -> ApplicationRead:
    return application_service.application_to_read(application_service.update_application(db, app_id, data))


@router.delete("/{app_id}", status_code=204)
def delete_application(app_id: int, db: Session = Depends(get_db)) -> None:
    application_service.delete_application(db, app_id)


@router.get("/{app_id}/resume.pdf")
def download_resume(app_id: int, db: Session = Depends(get_db)) -> FileResponse:
    app = application_service.get_application(db, app_id)
    if not app.resume_path or not Path(app.resume_path).exists():
        raise HTTPException(status_code=404, detail="No tailored resume PDF for this application yet")
    filename = f"{(app.company or 'resume').replace(' ', '_')}_{app.role.replace(' ', '_')}.pdf"
    return FileResponse(app.resume_path, media_type="application/pdf", filename=filename)


@router.post("/{app_id}/prepare", response_model=ApplicationRead)
async def prepare_application(
    app_id: int, body: PrepareRequest, request: Request, db: Session = Depends(get_db)
) -> ApplicationRead:
    preparer = getattr(request.app.state, "application_preparer", None)
    if preparer is None:
        raise HTTPException(status_code=503, detail="Application preparer is not initialised")
    app = application_service.get_application(db, app_id)
    app = await preparer.prepare(
        db, app, questions=body.questions, regenerate_resume=body.regenerate_resume, regenerate_answers=body.regenerate_answers
    )
    return application_service.application_to_read(app)


@router.post("/{app_id}/answer-questions", response_model=ApplicationRead)
async def answer_questions(
    app_id: int, body: AnswerQuestionsRequest, request: Request, db: Session = Depends(get_db)
) -> ApplicationRead:
    preparer = getattr(request.app.state, "application_preparer", None)
    if preparer is None:
        raise HTTPException(status_code=503, detail="Application preparer is not initialised")
    app = application_service.get_application(db, app_id)
    app = await preparer.answer_questions(db, app, body.questions)
    return application_service.application_to_read(app)


@router.post("/{app_id}/fill", response_model=FillResponse)
async def fill_application(app_id: int, body: FillRequest, request: Request, db: Session = Depends(get_db)) -> FillResponse:
    browser_agent = getattr(request.app.state, "browser_agent", None)
    if browser_agent is None:
        raise HTTPException(status_code=503, detail="Browser agent is not initialised")
    app = application_service.get_application(db, app_id)
    return await browser_agent.fill_application(db, app, url=body.url, headless=body.headless, submit=body.submit)


@router.post("/{app_id}/close-browser")
async def close_browser(app_id: int, request: Request) -> dict:
    browser_agent = getattr(request.app.state, "browser_agent", None)
    if browser_agent is None:
        raise HTTPException(status_code=503, detail="Browser agent is not initialised")
    closed = await browser_agent.close_session(app_id)
    return {"closed": closed}
