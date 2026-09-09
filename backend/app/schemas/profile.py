from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExperienceItem(BaseModel):
    title: str
    company: str
    start: str = ""
    end: str = ""          # "" or "Present"
    location: str = ""
    bullets: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class ProjectItem(BaseModel):
    name: str
    description: str = ""
    technologies: list[str] = Field(default_factory=list)
    url: str = ""
    bullets: list[str] = Field(default_factory=list)


class EducationItem(BaseModel):
    degree: str
    institution: str = ""
    year: str = ""
    details: str = ""


class ProfileBase(BaseModel):
    full_name: str
    email: str = ""
    phone: str = ""
    current_location: str = ""
    preferred_locations: list[str] = Field(default_factory=list)
    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""
    years_of_experience: float = 0
    notice_period: str = ""
    expected_salary: str = ""
    work_authorization: str = ""
    summary: str = ""

    current_role: str = ""
    current_company: str = ""
    experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)

    target_roles: list[str] = Field(default_factory=list)
    target_locations: list[str] = Field(default_factory=list)
    remote_preference: Literal["remote", "hybrid", "onsite", "any"] = "any"
    minimum_salary: int | None = None
    salary_currency: str = "INR"
    experience_min: int = 0
    experience_max: int = 6
    preferred_industries: list[str] = Field(default_factory=list)
    companies_to_avoid: list[str] = Field(default_factory=list)
    keywords_prioritize: list[str] = Field(default_factory=list)
    keywords_reject: list[str] = Field(default_factory=list)


class ProfileRead(ProfileBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProfileUpdate(BaseModel):
    """Partial update - every field optional."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    current_location: str | None = None
    preferred_locations: list[str] | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    portfolio_url: str | None = None
    years_of_experience: float | None = None
    notice_period: str | None = None
    expected_salary: str | None = None
    work_authorization: str | None = None
    summary: str | None = None
    current_role: str | None = None
    current_company: str | None = None
    experience: list[ExperienceItem] | None = None
    projects: list[ProjectItem] | None = None
    skills: list[str] | None = None
    technologies: list[str] | None = None
    education: list[EducationItem] | None = None
    achievements: list[str] | None = None
    certifications: list[str] | None = None
    target_roles: list[str] | None = None
    target_locations: list[str] | None = None
    remote_preference: Literal["remote", "hybrid", "onsite", "any"] | None = None
    minimum_salary: int | None = None
    salary_currency: str | None = None
    experience_min: int | None = None
    experience_max: int | None = None
    preferred_industries: list[str] | None = None
    companies_to_avoid: list[str] | None = None
    keywords_prioritize: list[str] | None = None
    keywords_reject: list[str] | None = None
