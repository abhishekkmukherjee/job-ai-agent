"""Schemas for every structured AI output.

The LLM is never allowed to return free-form decisions: each task has a strict
Pydantic model and the response is rejected if it does not validate.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models.enums import Recommendation, recommendation_for_score


def _clamp(v: Any, lo: int = 0, hi: int = 100) -> int:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, n))


class JobAnalysis(BaseModel):
    """Structured job evaluation (spec section 7)."""

    model_config = ConfigDict(extra="ignore")

    match_score: int = Field(ge=0, le=100)
    recommendation: Recommendation
    experience_match: int = Field(default=0, ge=0, le=100)
    skill_match: int = Field(default=0, ge=0, le=100)
    role_match: int = Field(default=0, ge=0, le=100)
    location_match: int = Field(default=0, ge=0, le=100)
    salary_match: int = Field(default=0, ge=0, le=100)
    reasoning: list[str] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    summary: str = ""

    @field_validator("match_score", "experience_match", "skill_match", "role_match", "location_match", "salary_match", mode="before")
    @classmethod
    def _clamp_scores(cls, v: Any) -> int:
        return _clamp(v)

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_conf(cls, v: Any) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.5
        if f > 1.0:  # model returned a percentage
            f = f / 100.0
        return max(0.0, min(1.0, f))

    @field_validator("recommendation", mode="before")
    @classmethod
    def _norm_recommendation(cls, v: Any) -> Any:
        if isinstance(v, str):
            s = v.strip().upper().replace(" ", "_").replace("-", "_")
            if s in {"LOW", "LOWPRIORITY"}:
                s = "LOW_PRIORITY"
            return s
        return v

    @field_validator("reasoning", "matched_skills", "missing_requirements", "red_flags", mode="before")
    @classmethod
    def _to_str_list(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        return [str(x).strip() for x in v if str(x).strip()]

    def enforce_recommendation_bands(self) -> "JobAnalysis":
        """The score decides the recommendation - never the model's free choice."""
        self.recommendation = recommendation_for_score(self.match_score)
        return self


class QuickFilterResult(BaseModel):
    """Cheap-model relevance check used before the expensive analysis."""

    model_config = ConfigDict(extra="ignore")

    relevant: bool
    reason: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("relevant", mode="before")
    @classmethod
    def _to_bool(cls, v: Any) -> bool:
        if isinstance(v, str):
            return v.strip().lower() in {"true", "yes", "1", "relevant"}
        return bool(v)

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_conf(cls, v: Any) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.5
        return max(0.0, min(1.0, f / 100.0 if f > 1 else f))


class ResumeExperience(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    company: str
    start: str = ""
    end: str = ""
    bullets: list[str] = Field(default_factory=list)


class ResumeProject(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    technologies: list[str] = Field(default_factory=list)


class TailoredResume(BaseModel):
    """Tailored resume produced ONLY from master-profile facts (spec section 8)."""

    model_config = ConfigDict(extra="ignore")

    headline: str = ""
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    experience: list[ResumeExperience] = Field(default_factory=list)
    projects: list[ResumeProject] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)
    tailoring_notes: list[str] = Field(default_factory=list)


class QuestionAnswer(BaseModel):
    """Answer to a single application question (spec section 9)."""

    model_config = ConfigDict(extra="ignore")

    question: str
    answer: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    needs_review: bool = False

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_conf(cls, v: Any) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.5
        return max(0.0, min(1.0, f / 100.0 if f > 1 else f))


class QuestionAnswerBatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answers: list[QuestionAnswer]


class AIStatus(BaseModel):
    providers: dict[str, dict[str, Any]]
    routes: dict[str, list[str]]
    cache_entries: int
