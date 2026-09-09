"""Supporting tables: AI result cache, search runs, pipeline failures, runtime settings."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Enum, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .types import TZDateTime
from .enums import SearchRunStatus


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AIResult(Base):
    """Cache of structured AI outputs.

    Key = (task, job_hash, profile_version, prompt_version).  If none of these
    change, the stored result is reused and no LLM call is made.
    """

    __tablename__ = "ai_results"
    __table_args__ = (
        UniqueConstraint("task", "job_hash", "profile_version", "prompt_version", name="uq_ai_result_key"),
        Index("ix_ai_results_job_hash", "job_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task: Mapped[str] = mapped_column(String(50), nullable=False)
    job_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    model: Mapped[str] = mapped_column(String(100), default="")
    provider: Mapped[str] = mapped_column(String(50), default="")
    result: Mapped[dict] = mapped_column(JSON, nullable=False)
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class SearchRun(Base):
    """One execution of the discovery pipeline (manual or scheduled)."""

    __tablename__ = "search_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trigger: Mapped[str] = mapped_column(String(30), default="manual")  # manual|scheduled|script
    status: Mapped[SearchRunStatus] = mapped_column(Enum(SearchRunStatus), default=SearchRunStatus.RUNNING)
    started_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")


class PipelineFailure(Base):
    """Stored failures so a single bad job never kills a run and can be debugged later."""

    __tablename__ = "pipeline_failures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage: Mapped[str] = mapped_column(String(50), nullable=False)   # source|normalize|filter|analysis|notify
    source: Mapped[str] = mapped_column(String(50), default="")
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    external_id: Mapped[str] = mapped_column(String(300), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)


class AppSetting(Base):
    """Editable runtime settings (filter rules, schedule, company career pages...).

    Stored as a single JSON document per key so new settings never need a migration.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)
