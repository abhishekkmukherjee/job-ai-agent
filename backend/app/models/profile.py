"""User profile - the single source of truth about the candidate.

Everything the AI is allowed to say about the candidate must come from here.
The `version` counter is bumped on every edit and forms part of the AI cache key
so stale analyses are never reused after the profile changes.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .types import TZDateTime


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    # --- personal information
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    current_location: Mapped[str] = mapped_column(String(200), default="")
    preferred_locations: Mapped[list] = mapped_column(JSON, default=list)
    linkedin_url: Mapped[str] = mapped_column(String(300), default="")
    github_url: Mapped[str] = mapped_column(String(300), default="")
    portfolio_url: Mapped[str] = mapped_column(String(300), default="")
    years_of_experience: Mapped[float] = mapped_column(Integer, default=0)
    notice_period: Mapped[str] = mapped_column(String(100), default="")
    expected_salary: Mapped[str] = mapped_column(String(100), default="")
    work_authorization: Mapped[str] = mapped_column(String(300), default="")
    summary: Mapped[str] = mapped_column(Text, default="")

    # --- professional profile (JSON lists of dicts / strings)
    current_role: Mapped[str] = mapped_column(String(200), default="")
    current_company: Mapped[str] = mapped_column(String(200), default="")
    experience: Mapped[list] = mapped_column(JSON, default=list)      # [{title, company, start, end, bullets[]}]
    projects: Mapped[list] = mapped_column(JSON, default=list)        # [{name, description, technologies[], url}]
    skills: Mapped[list] = mapped_column(JSON, default=list)          # ["Python", ...]
    technologies: Mapped[list] = mapped_column(JSON, default=list)
    education: Mapped[list] = mapped_column(JSON, default=list)       # [{degree, institution, year}]
    achievements: Mapped[list] = mapped_column(JSON, default=list)
    certifications: Mapped[list] = mapped_column(JSON, default=list)

    # --- job preferences
    target_roles: Mapped[list] = mapped_column(JSON, default=list)
    target_locations: Mapped[list] = mapped_column(JSON, default=list)
    remote_preference: Mapped[str] = mapped_column(String(30), default="any")  # remote|hybrid|onsite|any
    minimum_salary: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(10), default="INR")
    experience_min: Mapped[int] = mapped_column(Integer, default=0)
    experience_max: Mapped[int] = mapped_column(Integer, default=6)
    preferred_industries: Mapped[list] = mapped_column(JSON, default=list)
    companies_to_avoid: Mapped[list] = mapped_column(JSON, default=list)
    keywords_prioritize: Mapped[list] = mapped_column(JSON, default=list)
    keywords_reject: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)
