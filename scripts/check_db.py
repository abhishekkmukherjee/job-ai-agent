"""Verify that DATABASE_URL is reachable, create the tables and print row counts.

    python scripts/check_db.py
    DATABASE_URL=postgresql://... python scripts/check_db.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import func, select, text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.database import Base, get_engine, init_db, session_scope  # noqa: E402


def redact(url: str) -> str:
    if "@" in url and "://" in url:
        head, tail = url.split("://", 1)
        creds, host = tail.rsplit("@", 1)
        user = creds.split(":", 1)[0]
        return f"{head}://{user}:***@{host}"
    return url


def main() -> int:
    settings = get_settings()
    print("DATABASE_URL:", redact(settings.database_url))
    started = time.perf_counter()
    try:
        with get_engine().connect() as conn:
            version = conn.execute(text("select version()")).scalar()
    except Exception as e:  # noqa: BLE001
        print(f"CONNECTION FAILED after {time.perf_counter() - started:.1f}s: {type(e).__name__}: {e}")
        print("\nHints: use the *Session pooler* string from Supabase (port 5432, host aws-0-<region>.pooler.supabase.com),")
        print("       replace [YOUR-PASSWORD] with the database password (Settings -> Database), and keep the URL in quotes.")
        return 1
    print(f"connected in {time.perf_counter() - started:.1f}s: {str(version)[:80]}")
    init_db()
    print("tables ensured:", ", ".join(t.name for t in Base.metadata.sorted_tables))
    with session_scope() as db:
        for table in Base.metadata.sorted_tables:
            count = db.execute(select(func.count()).select_from(table)).scalar_one()
            print(f"  {table.name:<20} {count} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
