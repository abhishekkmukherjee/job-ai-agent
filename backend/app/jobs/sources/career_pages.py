"""Company career pages through public job-board APIs (Greenhouse, Lever, Ashby).

Company slugs are configured in Settings -> Company career pages.  These APIs are
public, documented and intended for exactly this kind of read access.
"""
from __future__ import annotations

from ...models.enums import RemoteType
from ...schemas.job import NormalizedJob
from ..normalize import html_to_text, infer_remote_type, parse_datetime
from .base import JobSource, SearchContext, query_matches


class _CareerPageSource(JobSource):
    config_key = ""
    requires = "company slugs in Settings -> Company career pages"

    def slugs(self, ctx: SearchContext) -> list[str]:
        return [s.strip() for s in (ctx.extra.get(self.config_key) or []) if s and s.strip()]

    def is_configured(self, ctx: SearchContext) -> bool:
        return bool(self.slugs(ctx))

    async def fetch(self, ctx: SearchContext) -> list[NormalizedJob]:
        jobs: list[NormalizedJob] = []
        for slug in self.slugs(ctx):
            jobs.extend(await self.fetch_company(slug, ctx))
            if len(jobs) >= ctx.max_results:
                break
        return jobs[: ctx.max_results]

    async def fetch_company(self, slug: str, ctx: SearchContext) -> list[NormalizedJob]:  # pragma: no cover
        raise NotImplementedError


def _company_name(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title()


class GreenhouseSource(_CareerPageSource):
    name = "greenhouse"
    config_key = "greenhouse"
    description = "Greenhouse job boards (boards-api.greenhouse.io) for configured companies."

    async def fetch_company(self, slug: str, ctx: SearchContext) -> list[NormalizedJob]:
        data = await self._get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", params={"content": "true"})
        out: list[NormalizedJob] = []
        for raw in data.get("jobs", []) or []:
            title = raw.get("title") or ""
            if not query_matches(title, ctx.queries):
                continue
            location = ((raw.get("location") or {}).get("name")) or ""
            out.append(
                NormalizedJob(
                    external_id=f"{slug}-{raw.get('id')}",
                    source=self.name,
                    title=title,
                    company=_company_name(slug),
                    location=location,
                    remote_type=infer_remote_type(location, title),
                    description=html_to_text(raw.get("content")),
                    url=raw.get("absolute_url") or "",
                    apply_url=raw.get("absolute_url") or "",
                    tags=[d.get("name", "") for d in (raw.get("departments") or []) if isinstance(d, dict) and d.get("name")],
                    posted_at=parse_datetime(raw.get("updated_at") or raw.get("first_published")),
                )
            )
        return out


class LeverSource(_CareerPageSource):
    name = "lever"
    config_key = "lever"
    description = "Lever postings API (api.lever.co) for configured companies."

    async def fetch_company(self, slug: str, ctx: SearchContext) -> list[NormalizedJob]:
        data = await self._get_json(f"https://api.lever.co/v0/postings/{slug}", params={"mode": "json"})
        out: list[NormalizedJob] = []
        for raw in data if isinstance(data, list) else []:
            title = raw.get("text") or ""
            if not query_matches(title, ctx.queries):
                continue
            cats = raw.get("categories") or {}
            location = cats.get("location") or ""
            workplace = (raw.get("workplaceType") or "").lower()
            remote = {
                "remote": RemoteType.REMOTE, "hybrid": RemoteType.HYBRID,
                "on-site": RemoteType.ONSITE, "onsite": RemoteType.ONSITE,
            }.get(workplace, infer_remote_type(location, title))
            out.append(
                NormalizedJob(
                    external_id=f"{slug}-{raw.get('id')}",
                    source=self.name,
                    title=title,
                    company=_company_name(slug),
                    location=location,
                    remote_type=remote,
                    description=html_to_text(raw.get("descriptionPlain") or raw.get("description")),
                    url=raw.get("hostedUrl") or "",
                    apply_url=raw.get("applyUrl") or raw.get("hostedUrl") or "",
                    tags=[t for t in [cats.get("team"), cats.get("department"), cats.get("commitment")] if t],
                    posted_at=parse_datetime(raw.get("createdAt")),
                )
            )
        return out


class AshbySource(_CareerPageSource):
    name = "ashby"
    config_key = "ashby"
    description = "Ashby job boards (api.ashbyhq.com) for configured companies."

    async def fetch_company(self, slug: str, ctx: SearchContext) -> list[NormalizedJob]:
        data = await self._get_json(
            f"https://api.ashbyhq.com/posting-api/job-board/{slug}", params={"includeCompensation": "true"}
        )
        out: list[NormalizedJob] = []
        for raw in data.get("jobs", []) or []:
            title = raw.get("title") or ""
            if not query_matches(title, ctx.queries):
                continue
            location = raw.get("location") or ""
            is_remote = bool(raw.get("isRemote"))
            out.append(
                NormalizedJob(
                    external_id=f"{slug}-{raw.get('id')}",
                    source=self.name,
                    title=title,
                    company=_company_name(slug),
                    location=location or ("Remote" if is_remote else ""),
                    remote_type=RemoteType.REMOTE if is_remote else infer_remote_type(location, title),
                    description=html_to_text(raw.get("descriptionHtml") or raw.get("descriptionPlain")),
                    url=raw.get("jobUrl") or "",
                    apply_url=raw.get("applyUrl") or raw.get("jobUrl") or "",
                    tags=[t for t in [raw.get("department"), raw.get("team"), raw.get("employmentType")] if t],
                    posted_at=parse_datetime(raw.get("publishedAt")),
                )
            )
        return out
