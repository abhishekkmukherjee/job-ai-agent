"""Housekeeping for search runs."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SearchRun, SearchRunStatus


def fail_interrupted_runs(db: Session) -> int:
    """At startup no run can legitimately be RUNNING: the process that owned it is gone."""
    rows = db.execute(select(SearchRun).where(SearchRun.status == SearchRunStatus.RUNNING)).scalars().all()
    for run in rows:
        run.status = SearchRunStatus.FAILED
        run.finished_at = datetime.now(timezone.utc)
        run.error = "Interrupted: the backend restarted while this run was in progress."
        db.add(run)
    if rows:
        db.commit()
    return len(rows)
