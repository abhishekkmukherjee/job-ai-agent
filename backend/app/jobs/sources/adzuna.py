"""Adzuna - official search API with a free developer tier; good India coverage.

Requires ADZUNA_APP_ID / ADZUNA_APP_KEY (https://developer.adzuna.com/).
"""
from __future__ import annotations

from ...schemas.job import NormalizedJob
from ..normalize import clean_text, infer_remote_type, parse_datetime, to_float
from .base import JobSource, SearchContext, query_matches

API_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
CURRENCY_BY_COUNTRY = {"in": "INR", "gb": "GBP", "us": "USD", "de": "EUR", "ca": "CAD", "au": "AUD", "sg": "SGD"}


class AdzunaSource(JobSource):
    name = "adzuna"
    description = "Adzuna search API (India + 15 countries, salary estimates). Free developer key required."
    requires = "ADZUNA_APP_ID and ADZUNA_APP_KEY"

    def __init__(self, app_id: str = "", app_key: str = "", country: str = "in", **kwargs):
        super().__init__(**kwargs)
        self.app_id = app_id
        self.app_key = app_key
        self.country = (country or "in").lower()

    def is_configured(self, ctx: SearchContext) -> bool:
        return bool(self.app_id and self.app_key)

    async def fetch(self, ctx: SearchContext) -> list[NormalizedJob]:
        jobs: list[NormalizedJob] = []
        seen: set[str] = set()
        locations = [loc for loc in ctx.locations if loc and loc.lower() != "remote"] or [""]
        for query in ctx.queries[:6]:
            for location in locations[:3]:
                params = {
                    "app_id": self.app_id, "app_key": self.app_key, "results_per_page": 50, "what": query,
                    "content-type": "application/json", "max_days_old": 30, "sort_by": "date",
                }
                if location:
                    params["where"] = location
                data = await self._get_json(API_URL.format(country=self.country, page=1), params=params)
                for raw in data.get("results", []) or []:
                    ext = str(raw.get("id") or "")
                    if not ext or ext in seen:
                        continue
                    seen.add(ext)
                    title = raw.get("title") or ""
                    if not query_matches(title, ctx.queries):
                        continue
                    loc = (raw.get("location") or {}).get("display_name") or location
                    category = (raw.get("category") or {}).get("label")
                    jobs.append(
                        NormalizedJob(
                            external_id=ext,
                            source=self.name,
                            title=clean_text(title),
                            company=(raw.get("company") or {}).get("display_name") or "",
                            location=loc,
                            remote_type=infer_remote_type(title, loc, raw.get("description")),
                            salary_min=to_float(raw.get("salary_min")),
                            salary_max=to_float(raw.get("salary_max")),
                            salary_currency=CURRENCY_BY_COUNTRY.get(self.country, ""),
                            description=clean_text(raw.get("description")),
                            url=raw.get("redirect_url") or "",
                            apply_url=raw.get("redirect_url") or "",
                            tags=[category] if category else [],
                            posted_at=parse_datetime(raw.get("created")),
                            raw={"contract_type": raw.get("contract_type"), "salary_is_predicted": raw.get("salary_is_predicted")},
                        )
                    )
                    if len(jobs) >= ctx.max_results:
                        return jobs
        return jobs
