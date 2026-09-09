"""Public job feeds that need no key: Himalayas (JSON API), We Work Remotely (RSS),
Hacker News "Who is hiring" (Algolia API)."""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import httpx

from ...models.enums import RemoteType
from ...schemas.job import NormalizedJob
from ..normalize import clean_text, html_to_text, infer_remote_type, parse_datetime, to_float
from .base import JobSource, SearchContext, SourceError, query_matches


class HimalayasSource(JobSource):
    name = "himalayas"
    description = "Himalayas remote jobs API (public, no key). Location restrictions are respected by the filter."

    API_URL = "https://himalayas.app/jobs/api"

    async def fetch(self, ctx: SearchContext) -> list[NormalizedJob]:
        jobs: list[NormalizedJob] = []
        seen: set[str] = set()
        cursor: str | None = None
        for _ in range(3):
            params = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            data = await self._get_json(self.API_URL, params=params)
            for raw in data.get("jobs", []) or []:
                ext = str(raw.get("guid") or raw.get("applicationLink") or "")
                title = raw.get("title") or ""
                if not ext or ext in seen or not title:
                    continue
                seen.add(ext)
                if not query_matches(title, ctx.queries):
                    continue
                restrictions = [r for r in (raw.get("locationRestrictions") or []) if isinstance(r, str)]
                location = f"Remote ({', '.join(restrictions)})" if restrictions else "Remote - Worldwide"
                yearly = (raw.get("salaryPeriod") or "").lower().startswith("year")
                jobs.append(
                    NormalizedJob(
                        external_id=ext,
                        source=self.name,
                        title=clean_text(title),
                        company=raw.get("companyName") or "",
                        location=location,
                        remote_type=RemoteType.REMOTE,
                        salary_min=to_float(raw.get("minSalary")) if yearly else None,
                        salary_max=to_float(raw.get("maxSalary")) if yearly else None,
                        salary_currency=(raw.get("currency") or "") if yearly else "",
                        description=html_to_text(raw.get("description") or raw.get("excerpt")),
                        url=raw.get("applicationLink") or ext,
                        apply_url=raw.get("applicationLink") or ext,
                        tags=[t for t in [raw.get("employmentType"), *(raw.get("seniority") or []), *(raw.get("categories") or [])[:5]] if isinstance(t, str)],
                        posted_at=parse_datetime(raw.get("pubDate")),
                        raw={"salaryPeriod": raw.get("salaryPeriod"), "timezoneRestrictions": raw.get("timezoneRestrictions")},
                    )
                )
                if len(jobs) >= ctx.max_results:
                    return jobs
            cursor = data.get("nextCursor")
            if not cursor:
                break
        return jobs


class WeWorkRemotelySource(JobSource):
    name = "weworkremotely"
    description = "We Work Remotely RSS feeds (programming + DevOps categories, no key)."

    FEEDS = [
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    ]

    async def _get_xml(self, url: str) -> ET.Element:
        try:
            async with self._client() as client:
                resp = await client.get(url, headers={"Accept": "application/rss+xml, application/xml"})
        except httpx.HTTPError as e:
            raise SourceError(f"{self.name}: {e}") from e
        if resp.status_code >= 400:
            raise SourceError(f"{self.name}: HTTP {resp.status_code}")
        try:
            return ET.fromstring(resp.content)
        except ET.ParseError as e:
            raise SourceError(f"{self.name}: invalid RSS") from e

    def parse_feed(self, root: ET.Element, ctx: SearchContext, seen: set[str]) -> list[NormalizedJob]:
        out: list[NormalizedJob] = []
        for item in root.findall("channel/item"):
            get = lambda tag: (item.findtext(tag) or "").strip()  # noqa: E731
            link = get("link") or get("guid")
            raw_title = get("title")
            if not link or link in seen or not raw_title:
                continue
            company, _, title = raw_title.partition(": ")
            if not title:
                company, title = "", raw_title
            if not query_matches(title, ctx.queries):
                continue
            seen.add(link)
            region = get("region") or "Anywhere in the World"
            out.append(
                NormalizedJob(
                    external_id=link,
                    source=self.name,
                    title=clean_text(title),
                    company=clean_text(company),
                    location=f"Remote ({region})" if region else "Remote",
                    remote_type=RemoteType.REMOTE,
                    description=html_to_text(get("description")),
                    url=link,
                    apply_url=link,
                    tags=[t for t in [get("category"), get("type")] if t],
                    posted_at=parse_datetime(get("pubDate")),
                )
            )
        return out

    async def fetch(self, ctx: SearchContext) -> list[NormalizedJob]:
        jobs: list[NormalizedJob] = []
        seen: set[str] = set()
        for url in self.FEEDS:
            try:
                root = await self._get_xml(url)
            except SourceError:
                continue
            jobs.extend(self.parse_feed(root, ctx, seen))
            if len(jobs) >= ctx.max_results:
                break
        return jobs[: ctx.max_results]


_ROLE_WORDS = re.compile(r"engineer|developer|scientist|architect|programmer|swe|sde|founding", re.I)


def parse_hn_comment(comment: dict, ctx: SearchContext) -> NormalizedJob | None:
    text_html = comment.get("text") or ""
    text = html_to_text(html.unescape(text_html))
    if not text:
        return None
    first_line = text.split("\n", 1)[0]
    parts = [clean_text(p) for p in re.split(r"\s\|\s|\s\|\s?|\s\|", first_line) if clean_text(p)]
    if len(parts) < 2:
        return None
    company = parts[0]
    title = next((p for p in parts[1:] if _ROLE_WORDS.search(p)), parts[1])
    location = next((p for p in parts[1:] if re.search(r"remote|onsite|on-site|hybrid|india|bangalore|bengaluru|pune|hyderabad|mumbai|delhi|chennai|san francisco|new york|london|berlin|europe|us\b|usa", p, re.I)), "")
    if not query_matches(title + " " + first_line, ctx.queries):
        return None
    created = parse_datetime(comment.get("created_at")) or (datetime.fromtimestamp(comment["created_at_i"], tz=timezone.utc) if comment.get("created_at_i") else None)
    cid = str(comment.get("id") or "")
    return NormalizedJob(
        external_id=cid,
        source="hn_hiring",
        title=title[:200],
        company=company[:200],
        location=location[:200],
        remote_type=infer_remote_type(first_line),
        description=text[:8000],
        url=f"https://news.ycombinator.com/item?id={cid}",
        apply_url=f"https://news.ycombinator.com/item?id={cid}",
        tags=["hacker-news"],
        posted_at=created,
        raw={"first_line": first_line[:300]},
    )


class HNHiringSource(JobSource):
    name = "hn_hiring"
    description = 'Hacker News monthly "Who is hiring?" thread via the public Algolia API (many apply-by-email startups).'

    SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
    ITEM_URL = "https://hn.algolia.com/api/v1/items/{id}"

    async def fetch(self, ctx: SearchContext) -> list[NormalizedJob]:
        data = await self._get_json(self.SEARCH_URL, params={"query": "who is hiring", "tags": "story,author_whoishiring", "hitsPerPage": 5})
        hits = [h for h in data.get("hits", []) if "who is hiring" in (h.get("title") or "").lower()]
        if not hits:
            return []
        thread = await self._get_json(self.ITEM_URL.format(id=hits[0]["objectID"]))
        jobs: list[NormalizedJob] = []
        for comment in thread.get("children", []) or []:
            if not comment.get("text"):
                continue
            try:
                job = parse_hn_comment(comment, ctx)
            except Exception:  # noqa: BLE001 - one odd comment must not break the feed
                continue
            if job is not None:
                jobs.append(job)
                if len(jobs) >= ctx.max_results:
                    break
        return jobs
