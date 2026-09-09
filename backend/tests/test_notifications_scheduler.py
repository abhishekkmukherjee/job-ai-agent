import logging

from app.config import Settings
from app.notifications.base import NotificationError, NotificationProvider
from app.notifications.console import ConsoleProvider
from app.notifications.email import EmailProvider
from app.notifications.report import build_daily_report
from app.notifications.service import Notifier, build_notifier
from app.notifications.telegram import TelegramProvider
from app.scheduler.scheduler import SearchScheduler
from app.schemas.settings import SchedulerSettings


class BoomProvider(NotificationProvider):
    name = "boom"

    def is_configured(self):
        return True

    async def send(self, subject, body):
        raise NotificationError("smtp exploded")


class MemoryProvider(NotificationProvider):
    name = "memory"

    def __init__(self):
        self.sent = []

    def is_configured(self):
        return True

    async def send(self, subject, body):
        self.sent.append((subject, body))


async def test_notifier_isolates_failures_and_skips_unconfigured(caplog):
    mem = MemoryProvider()
    notifier = Notifier([BoomProvider(), mem, TelegramProvider("", ""), ConsoleProvider()], "http://localhost:8000")
    with caplog.at_level(logging.INFO):
        results = await notifier.send("Subject", "Body")
    assert results["boom"]["ok"] is False and "exploded" in results["boom"]["error"]
    assert results["memory"]["ok"] is True and mem.sent == [("Subject", "Body")]
    assert results["telegram"] == {"ok": False, "error": "not configured"}
    assert results["console"]["ok"] is True
    assert "Subject" in caplog.text


def test_build_notifier_from_settings():
    n = build_notifier(Settings(notification_providers="console,email,telegram", smtp_host="", telegram_bot_token=""))
    assert [p["name"] for p in n.describe()] == ["console", "email", "telegram"]
    assert n.describe()[0]["configured"] is True and n.describe()[1]["configured"] is False
    assert [p["name"] for p in build_notifier(Settings(notification_providers="bogus")).describe()] == ["console"]
    assert EmailProvider("smtp.x", 587, "u", "p", "", "to@x").sender == "u"


async def test_daily_report_contains_counts_and_top_jobs(db):
    from sqlalchemy import select

    from app.models import Job, JobPipelineStatus, Recommendation

    job = db.execute(select(Job).where(Job.company == "Nimbus Labs")).scalars().one()
    job.match_score, job.recommendation, job.pipeline_status = 94, Recommendation.APPLY, JobPipelineStatus.ANALYZED
    db.commit()
    stats = {"new_jobs": 47, "strong_matches": 8, "analyzed": 20, "filtered_out": 5, "duplicates": 3}
    subject, body = build_daily_report(db, None, stats, "http://localhost:8000")
    assert subject == "Job Agent - 47 new jobs, 8 strong matches"
    assert "47 new jobs found" in body and "8 strong matches" in body
    assert "1. AI Engineer (LLM Applications) - Nimbus Labs - 94% (APPLY)" in body
    assert body.rstrip().endswith("http://localhost:8000")


class FakePipeline:
    is_running = False


async def test_scheduler_schedules_and_reports():
    s = SearchScheduler(FakePipeline(), Settings(scheduler_enabled=False, schedule_cron="0 8 * * *"))
    s.start(SchedulerSettings(enabled=True, cron="0 8 * * *", timezone="Asia/Kolkata"))
    try:
        d = s.describe()
        assert d["running"] is True and d["next_run"] and d["error"] == ""
        s.reschedule(SchedulerSettings(enabled=True, cron="not a cron", timezone="Asia/Kolkata"))
        d = s.describe()
        assert d["running"] is False and "invalid cron" in d["error"] and d["next_run"] is None
        s.reschedule(SchedulerSettings(enabled=False, cron="0 8 * * *"))
        assert s.describe()["running"] is False
    finally:
        s.shutdown()


def test_settings_scheduler_endpoint_reschedules(client):
    body = {"scheduler": {"enabled": True, "cron": "30 7 * * 1-5", "timezone": "Asia/Kolkata", "analyze": True, "notify": False}}
    r = client.patch("/api/settings", json=body)
    assert r.status_code == 200
    env = client.get("/api/settings/env").json()
    assert env["scheduler"]["cron"] == "30 7 * * 1-5" and env["scheduler"]["running"] is True
    r = client.post("/api/settings/notifications/test")
    assert r.status_code == 200 and r.json()["results"]["console"]["ok"] is True
