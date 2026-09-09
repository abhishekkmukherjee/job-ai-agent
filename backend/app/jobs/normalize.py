"""Helpers to turn raw source payloads into clean NormalizedJob fields."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup

from ..models.enums import RemoteType

_WS_RE = re.compile(r"[ \t\r\f\v]+")
_NL_RE = re.compile(r"\n{3,}")


def html_to_text(html: str | None) -> str:
    """Convert HTML job descriptions to readable plain text.

    All markup is dropped - the description is stored and rendered as text only,
    so nothing from a job posting can ever execute in the dashboard.
    """
    if not html:
        return ""
    if "<" not in html:
        return clean_text(html)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "iframe", "object", "embed"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for li in soup.find_all("li"):
        li.insert(0, "- ")
    for block in soup.find_all(["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "ul", "ol", "section"]):
        block.append("\n")
    return clean_text(soup.get_text())


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ").replace("​", "")
    text = _WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _NL_RE.sub("\n\n", text)
    return text.strip()


def parse_datetime(value: Any) -> datetime | None:
    """Parse ISO strings, epoch seconds/millis, or common date formats to aware UTC datetimes."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(value).strip()
    if not s:
        return None
    if s.isdigit():
        return parse_datetime(int(s))
    s = s.replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z", "%d/%m/%Y"):
        try:
            dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


_REMOTE_HINTS = ("remote", "work from home", "wfh", "anywhere", "distributed", "telecommute")
_HYBRID_HINTS = ("hybrid",)
_ONSITE_HINTS = ("onsite", "on-site", "on site", "in office", "in-office")


def infer_remote_type(*texts: str | None, default: RemoteType = RemoteType.UNKNOWN) -> RemoteType:
    joined = " ".join(t for t in texts if t).lower()
    if any(h in joined for h in _HYBRID_HINTS):
        return RemoteType.HYBRID
    if any(h in joined for h in _ONSITE_HINTS):
        return RemoteType.ONSITE
    if any(h in joined for h in _REMOTE_HINTS):
        return RemoteType.REMOTE
    return default


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        f = float(str(value).replace(",", "").strip())
        return f if f > 0 else None
    except ValueError:
        return None


def first_str(*values: Any) -> str:
    for v in values:
        if v:
            return str(v).strip()
    return ""
