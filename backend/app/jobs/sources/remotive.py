"""Remotive - public remote-jobs API (https://remotive.com/api/remote-jobs)."""
from __future__ import annotations

from ...models.enums import RemoteType
from ...schemas.job import NormalizedJob
from ..normalize import html_to_text, infer_remote_type, parse_datetime
from .base import JobSource, SearchContext, query_matches

API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveSource(JobSource):
    name = "remotive"
    description = "Remotive remote jobs API (software / AI categories, worldwide remote roles)."

    async def fetch(self, ctx: SearchContext) -> list[NormalizedJob]:
        jobs: list[NormalizedJob] = []
        seen: set[str] = set()
        for query in ctx.queries[:6]:
            data = await self._get_json(API_URL, params={"search": query, "limit": min(ctx.max_results, 100)})
            for raw in data.get("jobs", []) or []:
                ext = str(raw.get("id") or "")
                if not ext or ext in seen:
                    continue
                seen.add(ext)
                title = raw.get("title") or ""
                if not query_matches(title + " " + (raw.get("category") or ""), ctx.queries + ["engineer", "developer"]):
                    continue
                location = raw.get("candidate_required_location") or "Remote"
                jobs.append(
                    NormalizedJob(
                        external_id=ext,
                        source=self.name,
                        title=title,
                        company=raw.get("company_name") or "",
                        location=location,
                        remote_type=infer_remote_type(location, raw.get("job_type"), default=RemoteType.REMOTE),
                        description=html_to_text(raw.get("description")),
                        url=raw.get("url") or "",
                        apply_url=raw.get("url") or "",
                        tags=[t for t in (raw.get("tags") or []) if isinstance(t, str)][:20],
                        posted_at=parse_datetime(raw.get("publication_date")),
                        raw={"category": raw.get("category"), "job_type": raw.get("job_type"), "salary": raw.get("salary")},
                    )
                )
                if len(jobs) >= ctx.max_results:
                    return jobs
        return jobs
