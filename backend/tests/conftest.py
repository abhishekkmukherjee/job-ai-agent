"""Shared pytest fixtures.

Every test gets a fresh in-memory SQLite database seeded with the profile and
sample jobs.  No network access and no real AI provider is ever used unless a
test is explicitly marked `integration` and the required API key is present.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Must be set before any app module reads settings.
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SEED_ON_STARTUP"] = "false"
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["BROWSER_HEADLESS"] = "true"
os.environ["NOTIFICATION_PROVIDERS"] = "console"
os.environ.setdefault("GEMINI_API_KEY", "")
os.environ.setdefault("OPENROUTER_API_KEY", "")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import reset_settings_cache  # noqa: E402
from app.database import Base, configure_database, get_session_factory, init_db  # noqa: E402
from app.seed import seed_all  # noqa: E402


@pytest.fixture()
def db():
    reset_settings_cache()
    engine = configure_database("sqlite:///:memory:")
    init_db()
    session = get_session_factory()()
    seed_all(session, with_sample_jobs=True)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db):
    from app.main import app

    with TestClient(app) as c:
        yield c


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires real API keys / network")
    config.addinivalue_line("markers", "browser: requires Playwright browsers installed")
