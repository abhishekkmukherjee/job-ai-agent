"""Apply by email - for postings that say "send your CV to hr@company.com".

A legitimate, fully automatic channel: the tailored PDF is attached and a short
cover email is sent from the candidate's own mailbox.  Guards: one email per
job, never the same company twice within `per_company_days`, never to no-reply
or unsubscribe addresses, and never without a resume attachment.
"""
from __future__ import annotations

import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..logging_config import log_event
from ..models import Application

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.I)
_BAD_LOCAL = ("noreply", "no-reply", "donotreply", "do-not-reply", "unsubscribe", "privacy", "support", "billing", "abuse", "postmaster", "webmaster", "info@example")
_BAD_DOMAINS = ("example.com", "example.org", "linkedin.com", "indeed.com", "naukri.com", "glassdoor.com", "google.com", "facebook.com")
_APPLY_HINTS = re.compile(r"(send|email|mail|forward|share|submit|apply|drop)\b[^.\n]{0,80}\b(cv|resume|résumé|profile|application|portfolio)|\b(cv|resume)\b[^.\n]{0,60}\b(to|at)\b", re.I)


def find_application_email(text: str) -> str | None:
    """Return the address a candidate is asked to send their application to, if the posting names one."""
    if not text:
        return None
    candidates: list[tuple[int, str]] = []
    for m in _EMAIL_RE.finditer(text):
        addr = m.group(0).strip(".,;:)")
        local, _, domain = addr.lower().partition("@")
        if any(b in local for b in _BAD_LOCAL) or any(domain == d or domain.endswith("." + d) for d in _BAD_DOMAINS):
            continue
        window = text[max(0, m.start() - 160): m.end() + 60]
        score = 2 if _APPLY_HINTS.search(window) else 0
        if re.search(r"\b(hr|careers?|jobs?|hiring|recruit|talent|apply)\b", local + " " + window.lower()):
            score += 1
        candidates.append((score, addr))
    if not candidates:
        return None
    candidates.sort(key=lambda c: -c[0])
    score, addr = candidates[0]
    return addr if score >= 1 else None


class EmailApplier:
    def __init__(self, settings: Settings):
        self.settings = settings

    # ---------------------------------------------------------- config
    def _smtp_config(self) -> tuple[str, int, str, str, str, bool] | None:
        s = self.settings
        if s.smtp_host and s.smtp_username and s.smtp_password:
            return s.smtp_host, s.smtp_port, s.smtp_username, s.smtp_password, s.smtp_from or s.smtp_username, s.smtp_use_tls
        # Gmail: reuse the IMAP app password for sending only when explicitly allowed (keeps the main mailbox read-only)
        if s.smtp_use_imap_account and s.imap_user and s.imap_password and "gmail" in (s.imap_host or "").lower():
            return "smtp.gmail.com", 587, s.imap_user, s.imap_password, s.imap_user, True
        return None

    def is_configured(self) -> bool:
        return self._smtp_config() is not None

    # ---------------------------------------------------------- guards
    @staticmethod
    def recently_emailed_company(db: Session, company: str, days: int) -> bool:
        if not company:
            return False
        since = datetime.now(timezone.utc) - timedelta(days=days)
        rows = db.execute(select(Application).where(Application.company.ilike(company.strip()))).scalars().all()
        for a in rows:
            fr = a.fill_result or {}
            if fr.get("channel") == "email" and a.applied_at:
                applied = a.applied_at if a.applied_at.tzinfo else a.applied_at.replace(tzinfo=timezone.utc)
                if applied >= since:
                    return True
        return False

    # ------------------------------------------------------------ send
    def send(self, to_email: str, subject: str, body: str, resume_path: str | None, reply_to: str | None = None) -> dict:
        cfg = self._smtp_config()
        if cfg is None:
            raise RuntimeError("email applications need SMTP_* settings or Gmail IMAP_USER/IMAP_PASSWORD")
        host, port, user, password, sender, use_tls = cfg
        if not resume_path or not Path(resume_path).exists():
            raise RuntimeError("no resume PDF to attach")
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = to_email
        msg["Subject"] = subject
        if reply_to:
            msg["Reply-To"] = reply_to
        msg.set_content(body)
        data = Path(resume_path).read_bytes()
        msg.add_attachment(data, maintype="application", subtype="pdf", filename=Path(resume_path).name)
        self._deliver(host, port, user, password, use_tls, msg)
        log_event("APPLICATION_EMAILED", to=to_email, subject=subject, attachment=Path(resume_path).name)
        return {"channel": "email", "to": to_email, "subject": subject, "attachment": Path(resume_path).name, "at": datetime.now(timezone.utc).isoformat()}

    @staticmethod
    def _deliver(host: str, port: int, user: str, password: str, use_tls: bool, msg: EmailMessage) -> None:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            if use_tls:
                smtp.starttls()
                smtp.ehlo()
            smtp.login(user, password)
            smtp.send_message(msg)
