"""Orchestrates application preparation: tailored resume + grounded answers -> READY_TO_APPLY."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..logging_config import log_event
from ..models import Application, ApplicationStatus
from ..services import application_service
from ..services.profile_service import get_profile
from .question_answerer import DEFAULT_QUESTIONS, AnsweringFailed, QuestionAnswerer
from .resume_tailor import ResumeTailor, TailoringFailed


class ApplicationPreparer:
    def __init__(self, tailor: ResumeTailor, answerer: QuestionAnswerer):
        self.tailor = tailor
        self.answerer = answerer

    async def prepare(self, db: Session, app: Application, questions: list[str] | None = None, regenerate_resume: bool = False) -> Application:
        job = app.job
        if job is None:
            raise HTTPException(status_code=409, detail="Application has no job attached")
        profile = get_profile(db)
        if app.status in (ApplicationStatus.DISCOVERED, ApplicationStatus.SHORTLISTED):
            application_service.transition_status(db, app, ApplicationStatus.APPROVED, note="prepare requested")
        if app.status in (ApplicationStatus.APPROVED, ApplicationStatus.READY_TO_APPLY):
            application_service.transition_status(db, app, ApplicationStatus.PREPARING, note="generating material")
        db.commit()
        try:
            if regenerate_resume or not app.tailored_resume:
                resume, model = await self.tailor.generate(db, job, profile, force=regenerate_resume)
                self.tailor.attach(db, app, resume, profile, model)
            qs = questions or DEFAULT_QUESTIONS
            answers = await self.answerer.answer(db, job, qs, profile)
            existing = {a.get("question", "").strip().lower(): a for a in (app.answers or []) if isinstance(a, dict)}
            merged = []
            for a in answers:
                prev = existing.pop(a.question.strip().lower(), None)
                # keep a user-edited answer unless regeneration was explicitly requested
                if prev and prev.get("answer") and not prev.get("needs_review") and not regenerate_resume:
                    merged.append(prev)
                else:
                    merged.append(a.model_dump())
            merged.extend(existing.values())
            app.answers = merged
            app.last_error = ""
            application_service.transition_status(db, app, ApplicationStatus.READY_TO_APPLY, note="material generated")
            db.commit()
            db.refresh(app)
            log_event(
                "APPLICATION_PREPARED", application_id=app.id, job_id=job.id, answers=len(merged),
                needs_review=sum(1 for a in merged if a.get("needs_review")), resume=app.resume_version,
            )
            return app
        except (TailoringFailed, AnsweringFailed) as e:
            app.last_error = f"Preparation failed: {e}"[:1000]
            application_service.transition_status(db, app, ApplicationStatus.APPROVED, note="preparation failed")
            db.commit()
            log_event("APPLICATION_FAILED", application_id=app.id, stage="prepare", error=str(e)[:300])
            raise HTTPException(status_code=502, detail=app.last_error) from e

    async def answer_questions(self, db: Session, app: Application, questions: list[str]) -> Application:
        job = app.job
        if job is None:
            raise HTTPException(status_code=409, detail="Application has no job attached")
        try:
            answers = await self.answerer.answer(db, job, questions)
        except AnsweringFailed as e:
            raise HTTPException(status_code=502, detail=f"Answer generation failed: {e}") from e
        current = [a for a in (app.answers or []) if isinstance(a, dict)]
        asked = {a.question.strip().lower() for a in answers}
        current = [a for a in current if a.get("question", "").strip().lower() not in asked]
        app.answers = [*current, *[a.model_dump() for a in answers]]
        db.commit()
        db.refresh(app)
        return app
