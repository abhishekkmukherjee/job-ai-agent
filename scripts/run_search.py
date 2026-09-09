"""Run one discovery pipeline pass from the command line (cron / GitHub Actions friendly).

    python scripts/run_search.py                # all enabled sources, analyze, notify
    python scripts/run_search.py --no-analyze   # discovery + rule filtering only
    python scripts/run_search.py --sources remotive,arbeitnow --no-notify
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.application_preparer import ApplicationPreparer  # noqa: E402
from app.agents.job_analyzer import JobAnalyzer  # noqa: E402
from app.agents.question_answerer import QuestionAnswerer  # noqa: E402
from app.agents.resume_tailor import ResumeTailor  # noqa: E402
from app.ai.factory import build_ai_router  # noqa: E402
from app.browser.agent import BrowserAgent  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.database import init_db, session_scope  # noqa: E402
from app.jobs.pipeline import JobPipeline  # noqa: E402
from app.jobs.sources.registry import SourceRegistry  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402
from app.seed import seed_all  # noqa: E402


def build_notifier(settings):
    try:
        from app.notifications.service import build_notifier as _build

        return _build(settings)
    except ImportError:
        return None


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run the job discovery pipeline once")
    parser.add_argument("--sources", help="comma separated source names (default: enabled sources)")
    parser.add_argument("--no-analyze", action="store_true", help="skip AI analysis")
    parser.add_argument("--no-notify", action="store_true", help="skip the daily report notification")
    parser.add_argument("--max-per-source", type=int, default=None)
    args = parser.parse_args()

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    init_db()
    with session_scope() as db:
        seed_all(db, with_sample_jobs=False)

    ai_router = build_ai_router(settings)
    answerer = QuestionAnswerer(ai_router, settings)
    preparer = ApplicationPreparer(ResumeTailor(ai_router, settings), answerer)
    browser_agent = BrowserAgent(settings, answerer)
    pipeline = JobPipeline(
        SourceRegistry(settings), JobAnalyzer(ai_router, settings), settings, notifier=build_notifier(settings),
        preparer=preparer, browser_agent=browser_agent,
    )
    sources = [s.strip() for s in args.sources.split(",")] if args.sources else None
    with session_scope() as db:
        run = await pipeline.run(
            db, trigger="script", sources=sources, analyze=not args.no_analyze, notify=not args.no_notify,
            max_per_source=args.max_per_source,
        )
        print(json.dumps({"run_id": run.id, "status": run.status.value, "stats": run.stats, "error": run.error}, indent=2, default=str))
        await browser_agent.shutdown()
        return 0 if run.status.value == "COMPLETED" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
