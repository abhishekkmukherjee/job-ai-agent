"""Job-alert emails (LinkedIn, Naukri, Indeed, Glassdoor...) read from the user's own inbox over IMAP.

Those sites do not offer public APIs and forbid scraping, but they happily email
the user their matching jobs.  Reading one's own mailbox is entirely legitimate.
Each alert email yields the job title, company, location (best effort) and the
link to the posting; the description is whatever snippet the email contains.

Set IMAP_HOST / IMAP_USER / IMAP_PASSWORD (for Gmail: an App Password) in .env.
"""
from __future__ import annotations

import asyncio
import email
import imaplib
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.message import Message
from typing import Any
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from ...models.enums import RemoteType
from ...schemas.job import NormalizedJob
from ..normalize import clean_text, infer_remote_type
from .base import JobSource, SearchContext, SourceError, query_matches

# (pattern on the URL, name used as source suffix, how to build a stable external id)
JOB_URL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(?:[^/?]*-)?(\d+)", re.I), "linkedin"),
    (re.compile(r"naukri\.com/job-listings-[^?\s]*?-(\d{6,})", re.I), "naukri"),
    (re.compile(r"indeed\.com/(?:viewjob|rc/clk|pagead/clk)[^\s]*?[?&]jk=([0-9a-f]{8,})", re.I), "indeed"),
    (re.compile(r"glassdoor\.[a-z.]+/job-listing/[^?\s]*?(\d{8,})", re.I), "glassdoor"),
    (re.compile(r"foundit\.in/(?:job|jobs)/[^?\s]*?-(\d{6,})", re.I), "foundit"),
    (re.compile(r"shine\.com/jobs/[^?\s]*?/(\d{6,})", re.I), "shine"),
    (re.compile(r"instahyre\.com/job-(\d+)", re.I), "instahyre"),
    (re.compile(r"hirist\.(?:com|tech)/j/[^?\s]*?-(\d{5,})", re.I), "hirist"),
    (re.compile(r"wellfound\.com/jobs/(\d+)", re.I), "wellfound"),
]
_GENERIC_LINK_TEXT = re.compile(r"^(view|see|apply|easy apply|apply now|view job|see job|details|more|open|job|click here)[\s\w]*$", re.I)


def _decode(value: str | None) -> str:
    if not value:
        return ""
    parts = []
    for chunk, enc in decode_header(value):
        parts.append(chunk.decode(enc or "utf-8", "replace") if isinstance(chunk, bytes) else chunk)
    return "".join(parts)


def _html_body(msg: Message) -> str:
    html, text = "", ""
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        ctype = part.get_content_type()
        if ctype not in ("text/html", "text/plain"):
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            body = payload.decode(part.get_content_charset() or "utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        if ctype == "text/html" and not html:
            html = body
        elif ctype == "text/plain" and not text:
            text = body
    return html or f"<pre>{text}</pre>"


def _unwrap_tracking(url: str) -> str:
    """Alert emails wrap job links in tracking redirects; recover the real URL when it is a query parameter."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    for key in ("url", "u", "redirect", "target", "dest", "link"):
        for candidate in parse_qs(parsed.query).get(key, []):
            if candidate.startswith("http"):
                return candidate
    return url


def _match_job_url(url: str) -> tuple[str, str] | None:
    for pattern, board in JOB_URL_PATTERNS:
        m = pattern.search(url)
        if m:
            return board, m.group(1)
    return None


def _container_lines(anchor: Any) -> list[str]:
    """Text lines of the smallest block around the link (title, company, location...)."""
    node = anchor
    for _ in range(4):
        parent = node.parent
        if parent is None:
            break
        node = parent
        text = node.get_text("\n", strip=True)
        if text.count("\n") >= 1 and len(text) < 600:
            break
    lines = [clean_text(x) for x in node.get_text("\n", strip=True).split("\n")]
    return [x for x in lines if x and not _GENERIC_LINK_TEXT.match(x)]


_RECRUITER_SUBJECT = re.compile(r"(?:job|opening|opportunity|hiring|vacancy)\s*[|:\-]\s*(?P<title>.+?)(?:\s+(?:in|at|@)\s+(?P<location>[A-Za-z ,/&()-]{2,60}))?\s*$", re.I)


def parse_recruiter_email(html: str, subject: str, sender: str, received_at: datetime | None = None) -> NormalizedJob | None:
    """Naukri / Instahyre style recruiter broadcasts: one job per email, title in the subject, 'Apply now' link in the body."""
    m = _RECRUITER_SUBJECT.search(clean_text(re.sub(r"[^\w\s|:@&/,()-]", "", subject or "")))
    if not m:
        return None
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    apply_url = ""
    for a in soup.find_all("a", href=True):
        if re.search(r"apply", a.get_text(" ", strip=True), re.I) and a["href"].startswith("http"):
            apply_url = a["href"].strip()
            break
    text = clean_text(soup.get_text("\n", strip=True))
    company = re.sub(r"<.*?>", "", sender or "").split("<")[0].strip().strip('"') or "Recruiter"
    import hashlib

    key = "recruiter-" + hashlib.sha1(f"{subject}|{sender}|{received_at}".encode("utf-8")).hexdigest()[:16]
    title = clean_text(m.group("title"))[:200]
    location = clean_text(m.group("location") or "")[:200]
    if not title:
        return None
    return NormalizedJob(
        external_id=key,
        source="email_alerts",
        title=title,
        company=company[:200],
        location=location,
        remote_type=infer_remote_type(title, location, text[:2000], default=RemoteType.UNKNOWN),
        description=f"Recruiter email ({subject}).\n\n{text[:6000]}",
        url=apply_url,
        apply_url=apply_url,
        tags=["recruiter-email", "email-alert"],
        posted_at=received_at,
        raw={"board": "recruiter", "sender": sender, "subject": subject},
    )


def parse_alert_email(html: str, subject: str = "", sender: str = "", received_at: datetime | None = None) -> list[NormalizedJob]:
    """Extract job postings from one alert email.  Best effort - titles and links are reliable, the rest is heuristic."""
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    found: dict[str, NormalizedJob] = {}
    for a in soup.find_all("a", href=True):
        raw_url = a["href"].strip()
        url = _unwrap_tracking(raw_url)
        hit = _match_job_url(url) or _match_job_url(raw_url)
        if not hit:
            continue
        board, job_id = hit
        key = f"{board}-{job_id}"
        link_text = clean_text(a.get_text(" ", strip=True))
        lines = _container_lines(a)
        title = link_text if link_text and not _GENERIC_LINK_TEXT.match(link_text) else (lines[0] if lines else "")
        if not title or len(title) > 150:
            continue
        others = [x for x in lines if x != title]
        company = others[0] if others else ""
        location = ""
        for x in others[1:4]:
            if re.search(r"remote|hybrid|india|bengaluru|bangalore|mumbai|pune|hyderabad|delhi|chennai|gurgaon|noida|kolkata|,", x, re.I):
                location = x
                break
        # "Company · Location" on one line
        if company and (" · " in company or " • " in company):
            company, _, maybe_loc = re.split(r"\s[·•]\s", company, maxsplit=1) + [""] if False else (company.split(" · ")[0] if " · " in company else company.split(" • ")[0], "", (company.split(" · ")[1] if " · " in company else company.split(" • ")[1]))
            location = location or maybe_loc
        snippet = " ".join(others[:6])[:1500]
        if key in found:
            continue
        found[key] = NormalizedJob(
            external_id=key,
            source="email_alerts",
            title=title[:200],
            company=company[:200],
            location=location[:200],
            remote_type=infer_remote_type(title, location, snippet, default=RemoteType.UNKNOWN),
            description=f"From a {board} job alert email ({subject}).\n\n{snippet}".strip(),
            url=url,
            apply_url=url,
            tags=[board, "email-alert"],
            posted_at=received_at,
            raw={"board": board, "sender": sender, "subject": subject},
        )
    if not found:
        single = parse_recruiter_email(html, subject, sender, received_at)
        if single is not None:
            found[single.external_id] = single
    return list(found.values())


class EmailAlertsSource(JobSource):
    name = "email_alerts"
    description = "Your own job-alert emails (LinkedIn, Naukri, Indeed, Glassdoor...) read over IMAP - the legitimate way to get those boards' listings."
    requires = "IMAP_HOST, IMAP_USER, IMAP_PASSWORD (Gmail: App Password)"

    def __init__(self, host: str = "", port: int = 993, user: str = "", password: str = "", folder: str = "INBOX", days: int = 3, senders: list[str] | None = None, **kwargs):
        super().__init__(**kwargs)
        self.host, self.port, self.user, self.password, self.folder, self.days = host, port, user, password, folder, days
        self.senders = senders or ["linkedin.com", "naukri.com", "indeed.com", "glassdoor.com"]

    def is_configured(self, ctx: SearchContext) -> bool:
        return bool(self.host and self.user and self.password)

    def _fetch_messages(self) -> list[tuple[str, str, str, datetime | None]]:
        """Blocking IMAP fetch -> list of (subject, sender, html, date)."""
        since = (datetime.now(timezone.utc) - timedelta(days=self.days)).strftime("%d-%b-%Y")
        out: list[tuple[str, str, str, datetime | None]] = []
        try:
            box = imaplib.IMAP4_SSL(self.host, self.port, timeout=self.timeout)
            box.login(self.user, self.password)
            box.select(self.folder, readonly=True)
            for sender in self.senders:
                status, data = box.search(None, f'(SINCE {since} FROM "{sender}")')
                if status != "OK" or not data or not data[0]:
                    continue
                ids = data[0].split()[-40:]
                for mid in ids:
                    status, parts = box.fetch(mid, "(RFC822)")
                    if status != "OK" or not parts or not isinstance(parts[0], tuple):
                        continue
                    msg = email.message_from_bytes(parts[0][1])
                    subject = _decode(msg.get("Subject"))
                    frm = _decode(msg.get("From"))
                    date = None
                    try:
                        date = email.utils.parsedate_to_datetime(msg.get("Date"))
                    except Exception:  # noqa: BLE001
                        pass
                    out.append((subject, frm, _html_body(msg), date))
            box.logout()
        except (imaplib.IMAP4.error, OSError) as e:
            raise SourceError(f"{self.name}: IMAP error: {e}") from e
        return out

    async def fetch(self, ctx: SearchContext) -> list[NormalizedJob]:
        messages = await asyncio.to_thread(self._fetch_messages)
        jobs: list[NormalizedJob] = []
        seen: set[str] = set()
        for subject, sender, html, date in messages:
            for job in parse_alert_email(html, subject, sender, date):
                if job.external_id in seen:
                    continue
                seen.add(job.external_id)
                if ctx.queries and not query_matches(job.title, ctx.queries + ["engineer", "developer"]):
                    continue
                jobs.append(job)
                if len(jobs) >= ctx.max_results:
                    return jobs
        return jobs
