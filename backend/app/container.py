"""Builds long-lived components and attaches them to `app.state`."""
from __future__ import annotations

from fastapi import FastAPI

from .agents.application_preparer import ApplicationPreparer
from .agents.job_analyzer import JobAnalyzer
from .agents.question_answerer import QuestionAnswerer
from .agents.resume_tailor import ResumeTailor
from .ai.factory import build_ai_router
from .browser.agent import BrowserAgent
from .config import get_settings
from .database import session_scope
from .jobs.pipeline import JobPipeline
from .jobs.sources.registry import SourceRegistry
from .logging_config import get_logger
from .notifications.service import build_notifier
from .scheduler.scheduler import SearchScheduler
from .services.settings_service import get_runtime_settings

logger = get_logger(__name__)


async def build_components(app: FastAPI) -> None:
    settings = get_settings()
    ai_router = build_ai_router(settings)
    analyzer = JobAnalyzer(ai_router, settings)
    registry = SourceRegistry(settings)
    tailor = ResumeTailor(ai_router, settings)
    answerer = QuestionAnswerer(ai_router, settings)
    notifier = build_notifier(settings)
    preparer = ApplicationPreparer(tailor, answerer)
    browser_agent = BrowserAgent(settings, answerer)
    pipeline = JobPipeline(registry, analyzer, settings, notifier=notifier, preparer=preparer, browser_agent=browser_agent)
    scheduler = SearchScheduler(pipeline, settings)

    app.state.ai_router = ai_router
    app.state.job_analyzer = analyzer
    app.state.source_registry = registry
    app.state.notifier = notifier
    app.state.pipeline = pipeline
    app.state.resume_tailor = tailor
    app.state.application_preparer = preparer
    app.state.browser_agent = browser_agent
    app.state.scheduler = scheduler

    with session_scope() as db:
        runtime = get_runtime_settings(db)
    config = runtime.scheduler
    if settings.scheduler_enabled and not config.enabled:
        config.enabled = True  # env var can force it on; the dashboard can turn it off again
    try:
        scheduler.start(config)
    except Exception as e:  # noqa: BLE001 - scheduler problems must not stop the API
        logger.error("Scheduler failed to start: %s", e)

    configured = ai_router.configured_providers()
    if configured:
        logger.info("AI providers configured: %s", ", ".join(configured))
    else:
        logger.warning("No AI provider configured - set GEMINI_API_KEY, GROQ_API_KEY or OPENROUTER_API_KEY in .env")
    logger.info("Notifications: %s", ", ".join(f"{p['name']}({'ok' if p['configured'] else 'unconfigured'})" for p in notifier.describe()))
    if runtime.auto_apply.enabled:
        logger.warning("Auto-apply is ENABLED (min score %s, daily cap %s)", runtime.auto_apply.min_score, runtime.auto_apply.daily_cap)
    if scheduler.describe()["running"]:
        logger.info("Scheduler active: %s (%s), next run %s", config.cron, config.timezone, scheduler.describe()["next_run"])


async def shutdown_components(app: FastAPI) -> None:
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is not None:
        scheduler.shutdown()
    browser_agent = getattr(app.state, "browser_agent", None)
    if browser_agent is not None:
        await browser_agent.shutdown()
