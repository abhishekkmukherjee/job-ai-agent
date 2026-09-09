"""Duplicate detection.

Two layers:
1. (source, external_id) unique constraint - the same posting from the same source.
2. content hash of normalized title + company (+ location bucket) - the same posting
   syndicated across boards.  The later copy is stored with `duplicate_of_id` so it
   is never analyzed or shown twice.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse, urlunparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Job

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_NOISE_WORDS = {"the", "a", "an", "and", "or", "at", "in", "for", "of", "to", "with", "sr", "senior", "jr", "junior", "ii", "iii", "iv"}
_COMPANY_SUFFIXES = {"inc", "llc", "ltd", "limited", "pvt", "private", "corp", "corporation", "co", "gmbh", "plc", "technologies", "technology", "labs", "solutions"}


def normalize_title(title: str) -> str:
    tokens = [t for t in _NON_ALNUM.sub(" ", (title or "").lower()).split() if t and t not in _NOISE_WORDS]
    return " ".join(tokens)


def normalize_company(company: str) -> str:
    tokens = [t for t in _NON_ALNUM.sub(" ", (company or "").lower()).split() if t and t not in _COMPANY_SUFFIXES]
    return " ".join(tokens)


def normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        p = urlparse(url.strip())
    except ValueError:
        return url.strip().lower()
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", "", "")).lower()


def content_hash(title: str, company: str) -> str:
    key = f"{normalize_title(title)}|{normalize_company(company)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def find_duplicate(db: Session, *, source: str, external_id: str, title: str, company: str, url: str) -> Job | None:
    """Return the existing job this posting duplicates, or None."""
    existing = db.execute(select(Job).where(Job.source == source, Job.external_id == external_id)).scalars().first()
    if existing is not None:
        return existing
    if url:
        norm = normalize_url(url)
        if norm:
            candidates = db.execute(select(Job).where(Job.url.ilike(f"{norm}%"))).scalars().all()
            for c in candidates:
                if normalize_url(c.url) == norm:
                    return c
    if company:
        h = content_hash(title, company)
        return db.execute(select(Job).where(Job.content_hash == h, Job.duplicate_of_id.is_(None))).scalars().first()
    return None
