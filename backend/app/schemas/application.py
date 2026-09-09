from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..models.enums import ApplicationStatus


class AnswerItem(BaseModel):
    question: str
    answer: str = ""
    confidence: float = 0.5
    needs_review: bool = False
    field_selector: str | None = None
    edited: bool = False      # True once the user changed the text by hand - never overwritten by regeneration
    source: str = ""          # ai | user


class ApplicationCreate(BaseModel):
    job_id: int
    status: ApplicationStatus = ApplicationStatus.SHORTLISTED
    notes: str = ""


class ApplicationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ApplicationStatus | None = None
    notes: str | None = None
    follow_up_date: datetime | None = None
    interview_dates: list[str] | None = None
    rejection_reason: str | None = None
    applied_at: datetime | None = None
    answers: list[AnswerItem] | None = None
    cover_note: str | None = None
    tailored_resume: dict[str, Any] | None = None


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    company: str
    role: str
    job_url: str
    source: str
    match_score: int | None
    status: ApplicationStatus
    status_history: list[dict[str, Any]]
    resume_version: str
    resume_path: str
    tailored_resume: dict[str, Any] | None
    answers: list[dict[str, Any]]
    cover_note: str
    fill_result: dict[str, Any] | None
    prepared_at: datetime | None
    applied_at: datetime | None
    notes: str
    follow_up_date: datetime | None
    interview_dates: list[Any]
    rejection_reason: str
    last_error: str
    created_at: datetime
    updated_at: datetime
    recommendation: str | None = None
    has_resume_pdf: bool = False


class ApplicationListResponse(BaseModel):
    items: list[ApplicationRead]
    total: int


class PrepareRequest(BaseModel):
    questions: list[str] = Field(default_factory=list)
    regenerate_resume: bool = False
    regenerate_answers: bool = False   # also overwrite hand-edited answers


class AnswerQuestionsRequest(BaseModel):
    questions: list[str] = Field(min_length=1)


class FillRequest(BaseModel):
    url: str | None = None
    headless: bool | None = None


class FillResponse(BaseModel):
    ok: bool
    message: str
    fields_filled: int = 0
    questions_answered: int = 0
    resume_uploaded: bool = False
    fields: list[dict[str, Any]] = Field(default_factory=list)
    unmatched_fields: list[dict[str, Any]] = Field(default_factory=list)
    browser_open: bool = False
    resume: str = ""
