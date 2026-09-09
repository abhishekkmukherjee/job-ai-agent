from __future__ import annotations

import httpx

from .base import NotificationError, NotificationProvider


class TelegramProvider(NotificationProvider):
    name = "telegram"

    def __init__(self, bot_token: str, chat_id: str, timeout: float = 15.0):
        self.bot_token, self.chat_id, self.timeout = bot_token, chat_id, timeout

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    async def send(self, subject: str, body: str) -> None:
        if not self.is_configured():
            raise NotificationError("telegram provider not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
        text = f"{subject}\n\n{body}"
        if len(text) > 3900:
            text = text[:3900] + "\n..."
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json={"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True})
        except httpx.HTTPError as e:
            raise NotificationError(f"telegram: {e}") from e
        if resp.status_code != 200:
            raise NotificationError(f"telegram: HTTP {resp.status_code}: {resp.text[:200]}")
