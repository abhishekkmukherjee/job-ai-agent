"""Y Combinator jobs (Work at a Startup) - the public job listing pages embed their data as JSON.

No login, no CAPTCHA: the listing page is public and server-rendered (Inertia.js).
Applying requires a YC account, so these jobs are prepared for assisted mode.
"""
from __future__ import annotations

import html
import json
import re

import httpx

from ...schemas.job import NormalizedJob
from ..normalize import clean_text, infer_remote_type, parse_datetime
from .base import JobSource, SearchContext, SourceError, query_matches

BASE = "https://www.ycombinator.com"
ROLE_PAGES = ["/jobs/role/software-engineer", "/jobs/role/machine-learning-engineer", "/jobs/role/full-stack-engineer", "/jobs/role/backend-engineer", "/jobs"]
_DATA_PAGE_RE = re.compile(r'data-page="([^"]+)"')


def parse_job_postings(page_html: str) -> list[dict]:
    m = _DATA_PAGE_RE.search(page_html or "")
    if not m:
        return []
    try:
        page = json.loads(html.unescape(m.group(1)))
    except ValueError:
        return []
    postings = (page.get("props") or {}).get("jobPostings") or []
    return [p for p in postings if isinstance(p, dict)]


class YCombinatorSource(JobSource):
    name = "ycombinator"
    description = "Y Combinator startup jobs (public listing pages). Applying needs a YC login - handled in assisted mode."

    async def _get_html(self, path: str) -> str:
        try:
            async with self._client() as client:
                resp = await client.get(BASE + path, headers={"Accept": "text/html"})
        except httpx.HTTPError as e:
            raise SourceError(f"{self.name}: {e}") from e
        if resp.status_code >= 400:
            raise SourceError(f"{self.name}: HTTP {resp.status_code} for {path}")
        return resp.text

    async def fetch(self, ctx: SearchContext) -> list[NormalizedJob]:
        jobs: list[NormalizedJob] = []
        seen: set[str] = set()
        for path in ROLE_PAGES:
            try:
                page_html = await self._get_html(path)
            except SourceError:
                continue
            for raw in parse_job_postings(page_html):
                ext = str(raw.get("id") or "")
                title = raw.get("title") or ""
                if not ext or ext in seen or not title:
                    continue
                seen.add(ext)
                if not query_matches(title + " " + (raw.get("prettyRole") or ""), ctx.queries + ["engineer", "developer"]):
                    continue
                location = clean_text(raw.get("location") or "")
                url = BASE + raw["url"] if str(raw.get("url", "")).startswith("/") else (raw.get("url") or "")
                desc_parts = [
                    f"{raw.get('companyName', '')} ({raw.get('companyBatchName', '')}): {raw.get('companyOneLiner', '')}".strip(),
                    f"Role: {raw.get('prettyRole') or raw.get('role', '')} | Type: {raw.get('type', '')} | Experience: {raw.get('minExperience') or 'not specified'}",
                    f"Salary: {raw.get('salaryRange') or 'not specified'} | Equity: {raw.get('equityRange') or 'not specified'} | Visa: {raw.get('visa') or 'not specified'}",
                    f"Skills: {', '.join(raw.get('skills') or [])}" if raw.get("skills") else "",
                    "Apply on Work at a Startup (YC account required).",
                ]
                jobs.append(
                    NormalizedJob(
                        external_id=ext,
                        source=self.name,
                        title=clean_text(title),
                        company=raw.get("companyName") or "",
                        location=location,
                        remote_type=infer_remote_type(location, title),
                        description="\n".join(p for p in desc_parts if p),
                        url=url,
                        apply_url=url,
                        tags=[t for t in [raw.get("companyBatchName"), raw.get("type"), *(raw.get("skills") or [])[:8]] if t],
                        posted_at=parse_datetime(raw.get("createdAt")) if re.match(r"\d{4}-", str(raw.get("createdAt", ""))) else None,
                        raw={"salaryRange": raw.get("salaryRange"), "minExperience": raw.get("minExperience"), "visa": raw.get("visa"), "lastActive": raw.get("lastActive")},
                    )
                )
                if len(jobs) >= ctx.max_results:
                    return jobs
        return jobs
