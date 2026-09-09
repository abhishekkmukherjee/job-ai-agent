from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from .base import NotificationError, NotificationProvider


class EmailProvider(NotificationProvider):
    name = "email"

    def __init__(self, host: str, port: int, username: str, password: str, sender: str, recipient: str, use_tls: bool = True, timeout: float = 20.0):
        self.host, self.port, self.username, self.password = host, port, username, password
        self.sender, self.recipient, self.use_tls, self.timeout = sender or username, recipient, use_tls, timeout

    def is_configured(self) -> bool:
        return bool(self.host and self.recipient and self.sender)

    def _send_sync(self, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.sender
        msg["To"] = self.recipient
        msg.set_content(body)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
                smtp.ehlo()
                if self.use_tls:
                    smtp.starttls()
                    smtp.ehlo()
                if self.username:
                    smtp.login(self.username, self.password)
                smtp.send_message(msg)
        except (smtplib.SMTPException, OSError) as e:
            raise NotificationError(f"email: {type(e).__name__}: {e}") from e

    async def send(self, subject: str, body: str) -> None:
        if not self.is_configured():
            raise NotificationError("email provider not configured (SMTP_HOST / SMTP_TO / SMTP_FROM)")
        await asyncio.to_thread(self._send_sync, subject, body)
