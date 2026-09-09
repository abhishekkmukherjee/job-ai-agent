"""JSearch (RapidAPI) - Google for Jobs aggregation covering LinkedIn, Indeed, Naukri, Glassdoor and more.

This is the legal way to *see* those boards' listings: the free plan (200 requests/month)
is enough for a few searches per day.  Applications still happen on the employer's page
the listing points to.  Key: https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
"""
from __future__ import annotations

from ...models.enums import RemoteType
from ...schemas.job import NormalizedJob
from ..normalize import clean_text, html_to_text, infer_remote_type, parse_datetime, to_float
from .base import JobSource, SearchContext, query_matches

API_URL = "https://jsearch.p.rapidapi.com/search"


class JSearchSource(JobSource):
    name = "jsearch"
    description = "JSearch (RapidAPI): LinkedIn / Indeed / Naukri / Glassdoor listings via Google for Jobs. Free key, 200 requests/month."
    requires = "RAPIDAPI_KEY"

    def __init__(self, api_key: str = "", country: str = "in", max_queries: int = 6, **kwargs):
        super().__init__(**kwargs)
        self.api_key = api_key
        self.country = (country or "in").lower()
        self.max_queries = max_queries

    def is_configured(self, ctx: SearchContext) -> bool:
        return bool(self.api_key)

    async def fetch(self, ctx: SearchContext) -> list[NormalizedJob]:
        jobs: list[NormalizedJob] = []
        seen: set[str] = set()
        onsite = [loc for loc in ctx.locations if loc and loc.lower() != "remote"][:1]
        searches: list[tuple[str, bool]] = []
        for q in ctx.queries:
            for loc in onsite:
                searches.append((f"{q} in {loc}", False))
            if ctx.remote_ok:
                searches.append((f"{q} remote", True))
        headers = {"X-RapidAPI-Key": self.api_key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}
        for query, remote_only in searches[: self.max_queries]:
            params = {"query": query, "num_pages": 1, "page": 1, "date_posted": "week", "country": self.country}
            if remote_only:
                params["work_from_home"] = "true"
            data = await self._get_json(API_URL, params=params, headers=headers)
            for raw in data.get("data", []) or []:
                ext = str(raw.get("job_id") or "")
                title = raw.get("job_title") or ""
                if not ext or ext in seen or not title:
                    continue
                seen.add(ext)
                if not query_matches(title, ctx.queries):
                    continue
                location = ", ".join(x for x in [raw.get("job_city"), raw.get("job_state"), raw.get("job_country")] if x)
                remote = RemoteType.REMOTE if raw.get("job_is_remote") else infer_remote_type(title, location, raw.get("job_description"))
                apply_options = [
                    {"publisher": o.get("publisher"), "link": o.get("apply_link")}
                    for o in (raw.get("apply_options") or []) if isinstance(o, dict)
                ]
                url = raw.get("job_apply_link") or (apply_options[0]["link"] if apply_options else "")
                direct = url if raw.get("job_apply_is_direct") else None
                jobs.append(
                    NormalizedJob(
                        external_id=ext,
                        source=self.name,
                        title=clean_text(title),
                        company=raw.get("employer_name") or "",
                        location=location or ("Remote" if raw.get("job_is_remote") else ""),
                        remote_type=remote,
                        salary_min=to_float(raw.get("job_min_salary")),
                        salary_max=to_float(raw.get("job_max_salary")),
                        salary_currency=(raw.get("job_salary_currency") or "") if raw.get("job_min_salary") else "",
                        description=html_to_text(raw.get("job_description")),
                        url=url,
                        apply_url=direct or url,
                        tags=[t for t in [raw.get("job_publisher"), raw.get("job_employment_type")] if t],
                        posted_at=parse_datetime(raw.get("job_posted_at_datetime_utc") or raw.get("job_posted_at_timestamp")),
                        raw={"publisher": raw.get("job_publisher"), "apply_options": apply_options[:6], "direct": bool(raw.get("job_apply_is_direct"))},
                    )
                )
                if len(jobs) >= ctx.max_results:
                    return jobs
        return jobs
