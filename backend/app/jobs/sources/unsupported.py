"""Connector interfaces for platforms that cannot be automated reliably or legally.

LinkedIn, Naukri, Indeed, Glassdoor and similar sites require authentication,
protect their listings with CAPTCHAs / anti-bot systems, or forbid automated
access in their terms.  This project deliberately does NOT scrape them.

The classes below exist so the pipeline has a documented, disabled slot for each:
if an official API/partner access becomes available, implement `fetch` here and
enable the source.  Until then `is_configured` is always False and the source is
listed as "unsupported" in the dashboard.
"""
from __future__ import annotations

from ...schemas.job import NormalizedJob
from .base import JobSource, SearchContext


class _UnsupportedSource(JobSource):
    reason = ""
    requires = "official API access (not available)"

    def is_configured(self, ctx: SearchContext) -> bool:
        return False

    async def fetch(self, ctx: SearchContext) -> list[NormalizedJob]:
        raise RuntimeError(f"{self.name} is not supported: {self.reason}")


class LinkedInSource(_UnsupportedSource):
    name = "linkedin"
    description = "LinkedIn Jobs - NOT automated (login wall, anti-bot protection, ToS)."
    reason = "requires login and prohibits automated access"


class NaukriSource(_UnsupportedSource):
    name = "naukri"
    description = "Naukri - NOT automated (anti-bot protection, no public API)."
    reason = "no public API; site uses bot protection"


class IndeedSource(_UnsupportedSource):
    name = "indeed"
    description = "Indeed - NOT automated (publisher API discontinued, CAPTCHA protection)."
    reason = "no public API; CAPTCHA protected"
