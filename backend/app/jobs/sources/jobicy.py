"""Jobicy - public remote jobs API (https://jobicy.com/api/v2/remote-jobs)."""
from __future__ import annotations

from ...models.enums import RemoteType
from ...schemas.job import NormalizedJob
from ..normalize import html_to_text, parse_datetime, to_float
from .base import JobSource, SearchContext, query_matches

API_URL = "https://jobicy.com/api/v2/remote-jobs"


class JobicySource(JobSource):
    name = "jobicy"
    description = "Jobicy remote jobs API (worldwide, filtered by search tag)."

    async def fetch(self, ctx: SearchContext) -> list[NormalizedJob]:
        jobs: list[NormalizedJob] = []
        seen: set[str] = set()
        for query in ctx.queries[:5]:
            data = await self._get_json(API_URL, params={"count": 50, "tag": query})
            for raw in data.get("jobs", []) or []:
                ext = str(raw.get("id") or "")
                if not ext or ext in seen:
                    continue
                seen.add(ext)
                title = raw.get("jobTitle") or ""
                if not query_matches(title, ctx.queries):
                    continue
                jobs.append(
                    NormalizedJob(
                        external_id=ext,
                        source=self.name,
                        title=title,
                        company=raw.get("companyName") or "",
                        location=raw.get("jobGeo") or "Anywhere",
                        remote_type=RemoteType.REMOTE,
                        salary_min=to_float(raw.get("annualSalaryMin")),
                        salary_max=to_float(raw.get("annualSalaryMax")),
                        salary_currency=raw.get("salaryCurrency") or "",
                        description=html_to_text(raw.get("jobDescription") or raw.get("jobExcerpt")),
                        url=raw.get("url") or "",
                        apply_url=raw.get("url") or "",
                        tags=[t for t in (raw.get("jobIndustry") or []) if isinstance(t, str)][:10],
                        posted_at=parse_datetime(raw.get("pubDate")),
                        raw={"jobType": raw.get("jobType"), "jobLevel": raw.get("jobLevel")},
                    )
                )
                if len(jobs) >= ctx.max_results:
                    return jobs
        return jobs
