"""Jooble - aggregator API with an official free key (https://jooble.org/api/about). Good India coverage."""
from __future__ import annotations

from typing import Any

import httpx

from ...schemas.job import NormalizedJob
from ..normalize import clean_text, infer_remote_type, parse_datetime
from .base import JobSource, SearchContext, SourceError, query_matches

API_URL = "https://jooble.org/api/{key}"


class JoobleSource(JobSource):
    name = "jooble"
    description = "Jooble aggregator API (official free key). Indexes company sites and many boards, India included."
    requires = "JOOBLE_API_KEY"

    def __init__(self, api_key: str = "", **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key

    def is_configured(self, ctx: SearchContext) -> bool:
        return bool(self.api_key)

    async def _post_json(self, url: str, body: dict[str, Any]) -> Any:
        try:
            async with self._client() as client:
                resp = await client.post(url, json=body)
        except httpx.TimeoutException as e:
            raise SourceError(f"{self.name}: timeout") from e
        except httpx.HTTPError as e:
            raise SourceError(f"{self.name}: connection error: {e}") from e
        if resp.status_code >= 400:
            raise SourceError(f"{self.name}: HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as e:
            raise SourceError(f"{self.name}: invalid JSON") from e

    async def fetch(self, ctx: SearchContext) -> list[NormalizedJob]:
        jobs: list[NormalizedJob] = []
        seen: set[str] = set()
        locations = [loc for loc in ctx.locations if loc] or ["India"]
        for query in ctx.queries[:6]:
            for location in locations[:2]:
                data = await self._post_json(API_URL.format(key=self.api_key), {"keywords": query, "location": location, "page": 1})
                for raw in data.get("jobs", []) or []:
                    ext = str(raw.get("id") or raw.get("link") or "")
                    title = raw.get("title") or ""
                    if not ext or ext in seen or not title:
                        continue
                    seen.add(ext)
                    if not query_matches(title, ctx.queries):
                        continue
                    loc = raw.get("location") or location
                    jobs.append(
                        NormalizedJob(
                            external_id=ext,
                            source=self.name,
                            title=clean_text(title),
                            company=raw.get("company") or "",
                            location=loc,
                            remote_type=infer_remote_type(title, loc, raw.get("snippet")),
                            description=clean_text(raw.get("snippet")),
                            url=raw.get("link") or "",
                            apply_url=raw.get("link") or "",
                            tags=[t for t in [raw.get("type"), raw.get("source")] if t],
                            posted_at=parse_datetime(raw.get("updated")),
                            raw={"salary": raw.get("salary"), "source": raw.get("source")},
                        )
                    )
                    if len(jobs) >= ctx.max_results:
                        return jobs
        return jobs
