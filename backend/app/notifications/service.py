from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from ..config import Settings
from ..logging_config import log_event
from ..models import SearchRun
from .base import NotificationError, NotificationProvider
from .console import ConsoleProvider
from .email import EmailProvider
from .report import build_daily_report
from .telegram import TelegramProvider


class Notifier:
    def __init__(self, providers: list[NotificationProvider], dashboard_url: str):
        self.providers = providers
        self.dashboard_url = dashboard_url

    def describe(self) -> list[dict[str, Any]]:
        return [{"name": p.name, "configured": p.is_configured()} for p in self.providers]

    async def send(self, subject: str, body: str) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for provider in self.providers:
            if not provider.is_configured():
                results[provider.name] = {"ok": False, "error": "not configured"}
                continue
            try:
                await provider.send(subject, body)
                results[provider.name] = {"ok": True}
                log_event("NOTIFICATION_SENT", provider=provider.name, subject=subject)
            except (NotificationError, Exception) as e:  # noqa: BLE001 - one channel failing must not block others
                results[provider.name] = {"ok": False, "error": str(e)[:300]}
                log_event("NOTIFICATION_FAILED", provider=provider.name, error=str(e)[:300], level=logging.WARNING)
        return results

    async def send_event(self, title: str, lines: list[str], link: str | None = None) -> dict[str, Any]:
        """Short progress update (auto-applied, needs review, run failed...)."""
        body = "\n".join(lines)
        if link:
            body = f"{body}\n{link}" if body else link
        return await self.send(title, body)

    async def send_daily_report(self, db: Session, run: SearchRun | None, stats: dict[str, Any]) -> dict[str, Any]:
        subject, body = build_daily_report(db, run, stats, self.dashboard_url)
        return await self.send(subject, body)


def build_notifier(settings: Settings) -> Notifier:
    available: dict[str, NotificationProvider] = {
        "console": ConsoleProvider(),
        "email": EmailProvider(
            settings.smtp_host, settings.smtp_port, settings.smtp_username, settings.smtp_password,
            settings.smtp_from, settings.smtp_to, settings.smtp_use_tls,
        ),
        "telegram": TelegramProvider(settings.telegram_bot_token, settings.telegram_chat_id),
    }
    chosen = [available[n] for n in settings.notification_provider_list if n in available] or [available["console"]]
    return Notifier(chosen, settings.dashboard_url)
