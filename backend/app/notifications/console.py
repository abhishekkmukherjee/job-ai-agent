from __future__ import annotations

import logging

from .base import NotificationProvider

logger = logging.getLogger("job_agent.notifications")


class ConsoleProvider(NotificationProvider):
    name = "console"

    def is_configured(self) -> bool:
        return True

    async def send(self, subject: str, body: str) -> None:
        banner = "=" * 70
        logger.info("\n%s\n%s\n%s\n%s\n%s", banner, subject, "-" * 70, body, banner)
