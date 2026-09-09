"""JobSource interface + shared HTTP helper.

Rules for connectors (spec sections 5 and 25):
- Only public, documented APIs / feeds.  No login, no CAPTCHA, no anti-bot evasion.
- Every request has a timeout and a descriptive User-Agent.
- A failing source never breaks the run: the pipeline catches and records errors.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

from ...schemas.job import NormalizedJob


@dataclass
class SearchContext:
    """What a source needs to know to search."""

    queries: list[str]                       # e.g. ["AI Engineer", "Backend Engineer"]
    locations: list[str] = field(default_factory=list)
    remote_ok: bool = True
    max_results: int = 200
    extra: dict[str, Any] = field(default_factory=dict)   # per-source config (company slugs, api keys)


class SourceError(Exception):
    pass


class JobSource(ABC):
    name: str = "base"
    description: str = ""
    requires: str = ""          # human readable configuration requirement ("" = none)

    def __init__(self, timeout: float = 30.0, user_agent: str = "job-agent/0.1"):
        self.timeout = timeout
        self.user_agent = user_agent

    def is_configured(self, ctx: SearchContext) -> bool:
        return True

    @abstractmethod
    async def fetch(self, ctx: SearchContext) -> list[NormalizedJob]: ...

    # ---------------------------------------------------------------- http
    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.timeout,
            headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            follow_redirects=True,
        )

    async def _get_json(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> Any:
        try:
            async with self._client() as client:
                resp = await client.get(url, params=params, headers=headers)
        except httpx.TimeoutException as e:
            raise SourceError(f"{self.name}: timeout fetching {url}") from e
        except httpx.HTTPError as e:
            raise SourceError(f"{self.name}: connection error: {e}") from e
        if resp.status_code == 429:
            raise SourceError(f"{self.name}: rate limited (429) - try again later")
        if resp.status_code >= 400:
            raise SourceError(f"{self.name}: HTTP {resp.status_code} for {url}")
        try:
            return resp.json()
        except ValueError as e:
            raise SourceError(f"{self.name}: invalid JSON from {url}") from e

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "requires": self.requires}


def query_matches(text: str, queries: list[str]) -> bool:
    """Case-insensitive check whether any query term appears in text."""
    t = (text or "").lower()
    return any(q.lower() in t for q in queries if q)
