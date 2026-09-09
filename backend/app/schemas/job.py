from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models.enums import JobPipelineStatus, JobUserAction, Recommendation, RemoteType


class NormalizedJob(BaseModel):
    """The structure every JobSource must return (spec section 5)."""

    external_id: str
    source: str
    title: str
    company: str = ""
    location: str = ""
    remote_type: RemoteType = RemoteType.UNKNOWN
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = ""
    description: str = ""
    url: str = ""
    apply_url: str = ""
    tags: list[str] = Field(default_factory=list)
    posted_at: datetime | None = None
    raw: dict[str, Any] | None = None

    @field_validator("external_id", "title", mode="before")
    @classmethod
    def _not_blank(cls, v: Any) -> str:
        v = str(v or "").strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    source: str
    title: str
    company: str
    location: str
    remote_type: RemoteType
    salary_min: float | None
    salary_max: float | None
    salary_currency: str
    description: str
    url: str
    apply_url: str
    tags: list[str]
    posted_at: datetime | None
    discovered_at: datetime
    content_hash: str
    duplicate_of_id: int | None
    pipeline_status: JobPipelineStatus
    filter_reason: str
    filter_details: dict[str, Any]
    user_action: JobUserAction
    match_score: int | None
    recommendation: Recommendation | None
    analysis: dict[str, Any] | None
    analyzed_at: datetime | None
    analysis_model: str
    analysis_error: str
    is_sample: bool
    application_id: int | None = None
    application_status: str | None = None


class JobSummary(BaseModel):
    """Lighter representation for list views (no full description)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    title: str
    company: str
    location: str
    remote_type: RemoteType
    salary_min: float | None
    salary_max: float | None
    salary_currency: str
    url: str
    posted_at: datetime | None
    discovered_at: datetime
    pipeline_status: JobPipelineStatus
    filter_reason: str
    user_action: JobUserAction
    match_score: int | None
    recommendation: Recommendation | None
    analysis: dict[str, Any] | None
    is_sample: bool
    description_preview: str = ""
    application_id: int | None = None
    application_status: str | None = None


class JobListResponse(BaseModel):
    items: list[JobSummary]
    total: int
    page: int
    page_size: int


class JobUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_action: JobUserAction | None = None


class JobSearchRequest(BaseModel):
    sources: list[str] | None = None
    analyze: bool = True
    notify: bool = False
    max_per_source: int | None = Field(default=None, ge=1, le=1000)


class JobSearchResponse(BaseModel):
    run_id: int
    status: str
    message: str


class SearchRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    sources: list[str]
    stats: dict[str, Any]
    error: str


class PipelineFailureRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int | None
    stage: str
    source: str
    job_id: int | None
    external_id: str
    error: str
    created_at: datetime
