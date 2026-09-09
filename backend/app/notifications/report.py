"""Daily report text (spec section 14)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Application, ApplicationStatus, Job, JobPipelineStatus, JobUserAction, SearchRun


def build_daily_report(db: Session, run: SearchRun | None, stats: dict[str, Any], dashboard_url: str, top_n: int = 5) -> tuple[str, str]:
    stmt = (
        select(Job)
        .where(
            Job.pipeline_status == JobPipelineStatus.ANALYZED, Job.match_score.isnot(None),
            Job.user_action != JobUserAction.DISMISSED, Job.duplicate_of_id.is_(None),
        )
        .order_by(Job.match_score.desc(), Job.discovered_at.desc())
    )
    if run is not None and run.started_at is not None:
        recent = db.execute(stmt.where(Job.analyzed_at >= run.started_at).limit(top_n)).scalars().all()
        top = recent if recent else db.execute(stmt.limit(top_n)).scalars().all()
    else:
        top = db.execute(stmt.limit(top_n)).scalars().all()
    strong = sum(1 for j in top if (j.match_score or 0) >= 75)
    ready = db.execute(select(Application).where(Application.status == ApplicationStatus.READY_TO_APPLY)).scalars().all()

    new_jobs = stats.get("new_jobs", 0)
    strong_total = stats.get("strong_matches", strong)
    lines = ["Job Agent - Daily Report", ""]
    lines.append(f"{new_jobs} new jobs found")
    lines.append(f"{strong_total} strong matches")
    if stats.get("analyzed") is not None:
        lines.append(
            f"{stats.get('analyzed', 0)} analyzed, {stats.get('filtered_out', 0)} filtered out by rules, "
            f"{stats.get('duplicates', 0)} duplicates skipped"
        )
    if stats.get("failures"):
        lines.append(f"{stats['failures']} failure(s) recorded - see the Settings page")
    lines.append("")
    if top:
        lines.append("Top opportunities:")
        lines.append("")
        for i, j in enumerate(top, start=1):
            rec = j.recommendation.value if j.recommendation else ""
            lines.append(f"{i}. {j.title} - {j.company or 'unknown'} - {j.match_score}% ({rec})")
            if j.url:
                lines.append(f"   {j.url}")
        lines.append("")
    else:
        lines.append("No analyzed matches yet.")
        lines.append("")
    if ready:
        lines.append(f"{len(ready)} application(s) prepared and waiting for your review/submission.")
        lines.append("")
    lines.append("Open dashboard:")
    lines.append(dashboard_url)
    subject = f"Job Agent - {new_jobs} new jobs, {strong_total} strong matches"
    return subject, "\n".join(lines)
