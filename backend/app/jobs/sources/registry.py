"""Builds the set of available sources and reports their status."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ...config import Settings
from ...services.settings_service import get_runtime_settings
from .adzuna import AdzunaSource
from .arbeitnow import ArbeitnowSource
from .base import JobSource, SearchContext
from .career_pages import AshbySource, GreenhouseSource, LeverSource
from .jobicy import JobicySource
from .remoteok import RemoteOKSource
from .remotive import RemotiveSource
from .unsupported import IndeedSource, LinkedInSource, NaukriSource


class SourceRegistry:
    def __init__(self, settings: Settings, sources: list[JobSource] | None = None):
        self.settings = settings
        kwargs = {"timeout": settings.job_source_timeout, "user_agent": settings.job_user_agent}
        self.sources: dict[str, JobSource] = {
            s.name: s
            for s in (
                sources
                or [
                    RemotiveSource(**kwargs),
                    ArbeitnowSource(**kwargs),
                    RemoteOKSource(**kwargs),
                    JobicySource(**kwargs),
                    GreenhouseSource(**kwargs),
                    LeverSource(**kwargs),
                    AshbySource(**kwargs),
                    AdzunaSource(settings.adzuna_app_id, settings.adzuna_app_key, settings.adzuna_country, **kwargs),
                    LinkedInSource(**kwargs),
                    NaukriSource(**kwargs),
                    IndeedSource(**kwargs),
                ]
            )
        }

    def enabled_names(self, db: Session | None = None) -> list[str]:
        runtime = get_runtime_settings(db) if db is not None else None
        if runtime is not None and runtime.enabled_sources is not None:
            names = runtime.enabled_sources
        else:
            names = self.settings.enabled_sources
        return [n for n in names if n in self.sources]

    def build_context(self, db: Session, profile, max_results: int | None = None) -> SearchContext:
        runtime = get_runtime_settings(db)
        queries = list(dict.fromkeys([*(profile.target_roles or []), *(runtime.search_queries or [])]))
        return SearchContext(
            queries=queries or ["Software Engineer"],
            locations=list(profile.target_locations or profile.preferred_locations or []),
            remote_ok=(profile.remote_preference in ("remote", "hybrid", "any")),
            max_results=max_results or self.settings.job_source_max_per_source,
            extra={
                "greenhouse": runtime.career_pages.greenhouse,
                "lever": runtime.career_pages.lever,
                "ashby": runtime.career_pages.ashby,
            },
        )

    def describe(self, db: Session | None = None) -> list[dict[str, Any]]:
        enabled = set(self.enabled_names(db))
        ctx = SearchContext(queries=[], extra={})
        if db is not None:
            runtime = get_runtime_settings(db)
            ctx.extra = {"greenhouse": runtime.career_pages.greenhouse, "lever": runtime.career_pages.lever, "ashby": runtime.career_pages.ashby}
        out = []
        for name, src in self.sources.items():
            d = src.describe()
            d["enabled"] = name in enabled
            d["configured"] = src.is_configured(ctx)
            out.append(d)
        return out
