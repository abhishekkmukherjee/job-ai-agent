"""Application tracker model."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .types import TZDateTime
from .enums import ApplicationStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Application(Base):
    __tablename__ = "applications"
    # One application per job -> duplicate applications are impossible at the DB level.
    __table_args__ = (UniqueConstraint("job_id", name="uq_application_job"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    # Denormalized for the tracker table
    company: Mapped[str] = mapped_column(String(300), default="")
    role: Mapped[str] = mapped_column(String(300), default="")
    job_url: Mapped[str] = mapped_column(String(1000), default="")
    source: Mapped[str] = mapped_column(String(50), default="")
    match_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[ApplicationStatus] = mapped_column(Enum(ApplicationStatus), default=ApplicationStatus.DISCOVERED)
    status_history: Mapped[list] = mapped_column(JSON, default=list)  # [{status, at, note}]

    # Preparation artifacts
    resume_version: Mapped[str] = mapped_column(String(100), default="")   # e.g. "tailored-v3"
    resume_path: Mapped[str] = mapped_column(String(500), default="")      # PDF on disk
    tailored_resume: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # structured resume JSON
    answers: Mapped[list] = mapped_column(JSON, default=list)             # [{question, answer, confidence, needs_review}]
    cover_note: Mapped[str] = mapped_column(Text, default="")
    fill_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # last browser fill report
    prepared_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)

    # Tracking
    applied_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    follow_up_date: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    interview_dates: Mapped[list] = mapped_column(JSON, default=list)
    rejection_reason: Mapped[str] = mapped_column(String(500), default="")
    last_error: Mapped[str] = mapped_column(String(1000), default="")

    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    job = relationship("Job", back_populates="application")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Application {self.id} job={self.job_id} {self.status.value}>"
