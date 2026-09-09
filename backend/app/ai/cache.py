"""Database-backed cache for structured AI results (spec section 15)."""
from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import AIResult, Job


def job_hash_for(job: Job) -> str:
    """Hash of everything the model sees about a job."""
    payload = "\n".join(
        [
            (job.title or "").strip().lower(),
            (job.company or "").strip().lower(),
            (job.location or "").strip().lower(),
            (job.description or "").strip()[:12000],
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def text_hash(*parts: str) -> str:
    return hashlib.sha256("\n".join(p or "" for p in parts).encode("utf-8")).hexdigest()


class AIResultCache:
    def get(self, db: Session, task: str, job_hash: str, profile_version: int, prompt_version: int) -> AIResult | None:
        stmt = select(AIResult).where(
            AIResult.task == task,
            AIResult.job_hash == job_hash,
            AIResult.profile_version == profile_version,
            AIResult.prompt_version == prompt_version,
        )
        return db.execute(stmt).scalars().first()

    def put(
        self,
        db: Session,
        *,
        task: str,
        job_hash: str,
        profile_version: int,
        prompt_version: int,
        model: str,
        provider: str,
        result: dict[str, Any],
        usage: dict[str, Any] | None = None,
    ) -> AIResult:
        row = self.get(db, task, job_hash, profile_version, prompt_version)
        if row is None:
            row = AIResult(task=task, job_hash=job_hash, profile_version=profile_version, prompt_version=prompt_version, result={})
            db.add(row)
        row.model = model
        row.provider = provider
        row.result = result
        row.usage = usage
        db.flush()
        return row

    def count(self, db: Session) -> int:
        return db.execute(select(func.count(AIResult.id))).scalar_one()
