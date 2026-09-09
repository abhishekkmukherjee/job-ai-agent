from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AIResult
from ..schemas.settings import RuntimeSettings, RuntimeSettingsUpdate
from ..services import settings_service
from .deps import get_db

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=RuntimeSettings)
def read_settings(db: Session = Depends(get_db)) -> RuntimeSettings:
    return settings_service.get_runtime_settings(db)


@router.patch("", response_model=RuntimeSettings)
def patch_settings(data: RuntimeSettingsUpdate, request: Request, db: Session = Depends(get_db)) -> RuntimeSettings:
    updated = settings_service.update_runtime_settings(db, data)
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is not None and data.scheduler is not None:
        scheduler.reschedule(updated.scheduler)
    return updated


@router.get("/env")
def env_summary(request: Request, db: Session = Depends(get_db)) -> dict:
    """Non-secret view of environment configuration (keys are reported as configured/not)."""
    s = get_settings()
    ai_router = getattr(request.app.state, "ai_router", None)
    registry = getattr(request.app.state, "source_registry", None)
    scheduler = getattr(request.app.state, "scheduler", None)
    return {
        "app_env": s.app_env,
        "database": s.database_url.split("://", 1)[0],
        "gemini_configured": s.gemini_configured,
        "gemini_model": s.gemini_model,
        "openrouter_configured": s.openrouter_configured,
        "openrouter_model": s.openrouter_model,
        "adzuna_configured": bool(s.adzuna_app_id and s.adzuna_app_key),
        "notification_providers": s.notification_provider_list,
        "smtp_configured": bool(s.smtp_host and s.smtp_to),
        "telegram_configured": bool(s.telegram_bot_token and s.telegram_chat_id),
        "browser_headless": s.browser_headless,
        "ai": ai_router.status_summary() if ai_router else {},
        "sources": registry.describe(db) if registry else [],
        "scheduler": scheduler.describe() if scheduler else {"enabled": False},
        "ai_cache_entries": db.execute(select(func.count(AIResult.id))).scalar_one(),
        "prompt_versions": {
            "job_analysis": s.job_analysis_prompt_version,
            "resume_tailoring": s.resume_tailoring_prompt_version,
            "application_questions": s.application_questions_prompt_version,
            "job_filtering": s.job_filtering_prompt_version,
        },
    }


@router.post("/notifications/test")
async def test_notification(request: Request) -> dict:
    notifier = getattr(request.app.state, "notifier", None)
    if notifier is None:
        raise HTTPException(status_code=503, detail="Notifier not initialised")
    results = await notifier.send(
        "Job Agent - test notification", "This is a test notification from your Job Agent.\n\nEverything is wired up."
    )
    return {"results": results}


@router.post("/ai/test")
async def test_ai(request: Request) -> dict:
    ai_router = getattr(request.app.state, "ai_router", None)
    if ai_router is None:
        raise HTTPException(status_code=503, detail="AI router not initialised")
    return await ai_router.self_test()
