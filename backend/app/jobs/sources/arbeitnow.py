"""Arbeitnow - public job board API (https://www.arbeitnow.com/api/job-board-api)."""
from __future__ import annotations

from ...models.enums import RemoteType
from ...schemas.job import NormalizedJob
from ..normalize import html_to_text, infer_remote_type, parse_datetime
from .base import JobSource, SearchContext, query_matches

API_URL = "https://www.arbeitnow.com/api/job-board-api"


class ArbeitnowSource(JobSource):
    name = "arbeitnow"
    description = "Arbeitnow job board API (remote + Europe roles, visa-sponsorship flags)."

    async def fetch(self, ctx: SearchContext) -> list[NormalizedJob]:
        jobs: list[NormalizedJob] = []
        seen: set[str] = set()
        page = 1
        while len(jobs) < ctx.max_results and page <= 5:
            data = await self._get_json(API_URL, params={"page": page})
            items = data.get("data") or []
            if not items:
                break
            for raw in items:
                ext = str(raw.get("slug") or raw.get("url") or "")
                if not ext or ext in seen:
                    continue
                seen.add(ext)
                title = raw.get("title") or ""
                tags = [t for t in (raw.get("tags") or []) if isinstance(t, str)]
                if not query_matches(title + " " + " ".join(tags), ctx.queries):
                    continue
                is_remote = bool(raw.get("remote"))
                location = raw.get("location") or ("Remote" if is_remote else "")
                jobs.append(
                    NormalizedJob(
                        external_id=ext,
                        source=self.name,
                        title=title,
                        company=raw.get("company_name") or "",
                        location=location,
                        remote_type=RemoteType.REMOTE if is_remote else infer_remote_type(location, title),
                        description=html_to_text(raw.get("description")),
                        url=raw.get("url") or "",
                        apply_url=raw.get("url") or "",
                        tags=tags[:20],
                        posted_at=parse_datetime(raw.get("created_at")),
                        raw={"job_types": raw.get("job_types")},
                    )
                )
                if len(jobs) >= ctx.max_results:
                    break
            if not (data.get("links") or {}).get("next"):
                break
            page += 1
        return jobs
