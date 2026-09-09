"""RemoteOK - public JSON feed (https://remoteok.com/api).  Attribution is required by their terms."""
from __future__ import annotations

from ...models.enums import RemoteType
from ...schemas.job import NormalizedJob
from ..normalize import html_to_text, parse_datetime, to_float
from .base import JobSource, SearchContext, query_matches

API_URL = "https://remoteok.com/api"


class RemoteOKSource(JobSource):
    name = "remoteok"
    description = "RemoteOK public feed (remote tech jobs, often with salary ranges)."

    async def fetch(self, ctx: SearchContext) -> list[NormalizedJob]:
        data = await self._get_json(API_URL)
        jobs: list[NormalizedJob] = []
        if not isinstance(data, list):
            return jobs
        for raw in data:
            if not isinstance(raw, dict) or "id" not in raw or not raw.get("position"):
                continue  # the first element is a legal notice, not a job
            title = raw.get("position") or ""
            tags = [t for t in (raw.get("tags") or []) if isinstance(t, str)]
            if not query_matches(title + " " + " ".join(tags), ctx.queries):
                continue
            jobs.append(
                NormalizedJob(
                    external_id=str(raw["id"]),
                    source=self.name,
                    title=title,
                    company=raw.get("company") or "",
                    location=raw.get("location") or "Remote",
                    remote_type=RemoteType.REMOTE,
                    salary_min=to_float(raw.get("salary_min")),
                    salary_max=to_float(raw.get("salary_max")),
                    salary_currency="USD" if raw.get("salary_min") else "",
                    description=html_to_text(raw.get("description")),
                    url=raw.get("url") or "",
                    apply_url=raw.get("apply_url") or raw.get("url") or "",
                    tags=tags[:20],
                    posted_at=parse_datetime(raw.get("date") or raw.get("epoch")),
                )
            )
            if len(jobs) >= ctx.max_results:
                break
        return jobs
