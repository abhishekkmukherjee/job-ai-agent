"""APScheduler wrapper.  The cron expression + timezone live in runtime settings
(editable from the dashboard) with environment defaults - nothing is hard-coded."""
from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import Settings
from ..database import session_scope
from ..logging_config import log_event
from ..schemas.settings import SchedulerSettings

JOB_ID = "daily-job-search"


class SearchScheduler:
    def __init__(self, pipeline: Any, settings: Settings):
        self.pipeline = pipeline
        self.settings = settings
        self.scheduler = AsyncIOScheduler()
        self.config = SchedulerSettings(
            enabled=settings.scheduler_enabled, cron=settings.schedule_cron, timezone=settings.schedule_timezone
        )
        self.error = ""
        self._started = False

    def start(self, config: SchedulerSettings | None = None) -> None:
        if config is not None:
            self.config = config
        if not self._started:
            self.scheduler.start()
            self._started = True
        self.reschedule(self.config)

    def reschedule(self, config: SchedulerSettings) -> None:
        self.config = config
        self.error = ""
        if self._started and self.scheduler.get_job(JOB_ID):
            self.scheduler.remove_job(JOB_ID)
        if not config.enabled:
            return
        try:
            trigger = CronTrigger.from_crontab(config.cron, timezone=config.timezone or None)
        except (ValueError, TypeError) as e:
            self.error = f"invalid cron '{config.cron}': {e}"
            logging.getLogger(__name__).error(self.error)
            return
        if self._started:
            self.scheduler.add_job(
                self._run_scheduled, trigger, id=JOB_ID, replace_existing=True, misfire_grace_time=3600, coalesce=True
            )
            log_event("SCHEDULER_STARTED", cron=config.cron, timezone=config.timezone, next_run=str(self.next_run()))

    async def _run_scheduled(self) -> None:
        if self.pipeline.is_running:
            return
        with session_scope() as db:
            run = self.pipeline.create_run(db, trigger="scheduled")
            await self.pipeline.run(db, run=run, analyze=self.config.analyze, notify=self.config.notify)

    def next_run(self):
        job = self.scheduler.get_job(JOB_ID) if self._started else None
        return job.next_run_time if job else None

    def describe(self) -> dict[str, Any]:
        nxt = self.next_run()
        return {
            "enabled": self.config.enabled, "cron": self.config.cron, "timezone": self.config.timezone,
            "running": bool(self._started and self.config.enabled and not self.error),
            "next_run": nxt.isoformat() if nxt else None, "error": self.error,
        }

    def shutdown(self) -> None:
        if self._started:
            self.scheduler.shutdown(wait=False)
            self._started = False
