"""Copy every table from the local SQLite database into a Postgres database.

    python scripts/migrate_sqlite_to_postgres.py --target "postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"

The source defaults to ./data/job_agent.db (override with --source).  Tables are
created on the target if missing, copied in dependency order, and Postgres
sequences are reset so new rows get fresh ids.  Rows whose id already exists on
the target are skipped, so the script can be re-run safely.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import create_engine, func, insert, select, text  # noqa: E402

from app import models  # noqa: E402,F401  (registers tables)
from app.config import Settings  # noqa: E402
from app.database import Base  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy the SQLite database into Postgres")
    parser.add_argument("--source", default="sqlite:///" + (ROOT / "data" / "job_agent.db").as_posix())
    parser.add_argument("--target", required=True, help="Postgres URL (postgresql://user:password@host:5432/dbname)")
    parser.add_argument("--batch", type=int, default=500)
    args = parser.parse_args()

    source_url = Settings(database_url=args.source).database_url
    target_url = Settings(database_url=args.target).database_url
    if not target_url.startswith("postgresql"):
        print("target must be a PostgreSQL URL", file=sys.stderr)
        return 2

    src = create_engine(source_url, future=True)
    dst = create_engine(target_url, future=True, pool_pre_ping=True)
    Base.metadata.create_all(dst)

    total = 0
    with src.connect() as s, dst.begin() as d:
        for table in Base.metadata.sorted_tables:
            pk_cols = list(table.primary_key.columns)
            existing: set = set()
            if pk_cols:
                existing = {row[0] for row in d.execute(select(pk_cols[0])).all()}
            rows = [dict(r._mapping) for r in s.execute(select(table)).all()]
            if pk_cols:
                rows = [r for r in rows if r[pk_cols[0].name] not in existing]
            for i in range(0, len(rows), args.batch):
                d.execute(insert(table), rows[i : i + args.batch])
            total += len(rows)
            print(f"  {table.name:<20} copied {len(rows)} rows (skipped {len(existing)} existing)")
            # reset the sequence for integer primary keys
            if pk_cols and pk_cols[0].type.python_type is int:
                col = pk_cols[0].name
                d.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{table.name}', '{col}'), "
                        f"COALESCE((SELECT MAX({col}) FROM {table.name}), 0) + 1, false)"
                    )
                )
    with dst.connect() as d:
        jobs = d.execute(select(func.count()).select_from(Base.metadata.tables["jobs"])).scalar_one()
    print(f"done: {total} rows copied; target now has {jobs} jobs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
