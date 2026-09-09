from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DashboardCounts(BaseModel):
    jobs_discovered: int = 0
    jobs_discovered_today: int = 0
    strong_matches: int = 0
    strong_matches_today: int = 0
    recommended_applications: int = 0
    applications_submitted: int = 0
    interviews: int = 0
    pending_review: int = 0
    ready_to_apply: int = 0


class DashboardResponse(BaseModel):
    counts: DashboardCounts
    top_jobs: list[dict[str, Any]] = Field(default_factory=list)
    recent_applications: list[dict[str, Any]] = Field(default_factory=list)
    last_run: dict[str, Any] | None = None
    ai: dict[str, Any] = Field(default_factory=dict)
    sources: list[dict[str, Any]] = Field(default_factory=list)
