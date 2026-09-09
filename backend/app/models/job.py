"""Job model - a normalized posting from any source."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Enum, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .types import TZDateTime
from .enums import JobPipelineStatus, JobUserAction, Recommendation, RemoteType


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_job_source_external_id"),
        Index("ix_jobs_content_hash", "content_hash"),
        Index("ix_jobs_match_score", "match_score"),
        Index("ix_jobs_discovered_at", "discovered_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(300), nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    company: Mapped[str] = mapped_column(String(300), default="")
    location: Mapped[str] = mapped_column(String(300), default="")
    remote_type: Mapped[RemoteType] = mapped_column(Enum(RemoteType), default=RemoteType.UNKNOWN)
    salary_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_currency: Mapped[str] = mapped_column(String(10), default="")
    description: Mapped[str] = mapped_column(Text, default="")   # plain text, sanitized
    url: Mapped[str] = mapped_column(String(1000), default="")
    apply_url: Mapped[str] = mapped_column(String(1000), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    posted_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)

    # dedupe
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    duplicate_of_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # pipeline / filter state
    pipeline_status: Mapped[JobPipelineStatus] = mapped_column(Enum(JobPipelineStatus), default=JobPipelineStatus.NEW)
    filter_reason: Mapped[str] = mapped_column(String(500), default="")
    filter_details: Mapped[dict] = mapped_column(JSON, default=dict)
    user_action: Mapped[JobUserAction] = mapped_column(Enum(JobUserAction), default=JobUserAction.NONE)

    # AI analysis (denormalized for fast filtering + full JSON blob)
    match_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recommendation: Mapped[Recommendation | None] = mapped_column(Enum(Recommendation), nullable=True)
    analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    analyzed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    analysis_model: Mapped[str] = mapped_column(String(100), default="")
    analysis_error: Mapped[str] = mapped_column(String(500), default="")

    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)

    application = relationship("Application", back_populates="job", uselist=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Job {self.id} {self.title!r} @ {self.company!r} [{self.source}]>"
