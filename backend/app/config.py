"""Application configuration.

All runtime configuration is read from environment variables / a `.env` file
via pydantic-settings.  Nothing secret is hard-coded here.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root.  config.py lives at backend/app/config.py
ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
PROMPTS_DIR = ROOT_DIR / "prompts"
DATA_DIR = ROOT_DIR / "data"
FRONTEND_DIST_DIR = ROOT_DIR / "frontend" / "dist"
FAKE_JOB_SITE_DIR = ROOT_DIR / "fake-job-site"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ app
    app_name: str = "Job Agent"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "text"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    dashboard_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    seed_on_startup: bool = True
    serve_fake_job_site: bool = True

    # ------------------------------------------------------------- database
    database_url: str = "sqlite:///" + (DATA_DIR / "job_agent.db").as_posix()

    # ------------------------------------------------------------------- ai
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_fallback_model: str = "gemini-2.5-flash-lite"
    gemini_thinking_budget: int | None = None  # set 0 to disable thinking on 2.5 models
    gemini_min_interval: float = 4.0  # seconds between requests (free tier ~15 RPM)

    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemma-4-31b-it:free"
    openrouter_fallback_model: str = "openrouter/free"
    openrouter_json_mode: bool = False
    openrouter_site_url: str = "http://localhost:8000"
    openrouter_app_name: str = "job-agent"
    openrouter_min_interval: float = 3.0  # seconds between requests (free models ~20 RPM)

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_fallback_model: str = "openai/gpt-oss-20b"
    groq_min_interval: float = 2.5  # free tier ~30 RPM

    # Model routing: comma separated provider chain per task type.
    # Each entry is "provider" or "provider:model".
    ai_route_classification: str = "groq,openrouter,gemini"
    ai_route_job_analysis: str = "gemini,groq,openrouter"
    ai_route_resume_tailoring: str = "gemini,groq,openrouter"
    ai_route_application_questions: str = "gemini,groq,openrouter"
    ai_route_fallback: str = "openrouter"

    ai_request_timeout: float = 60.0
    ai_max_retries: int = 3
    ai_backoff_base: float = 1.5
    ai_backoff_max: float = 20.0
    ai_quick_filter_enabled: bool = True
    ai_max_analyses_per_run: int = 40
    ai_min_score_for_report: int = 75

    # Prompt versions (part of the AI cache key)
    job_analysis_prompt_version: int = 1
    resume_tailoring_prompt_version: int = 1
    application_questions_prompt_version: int = 2
    job_filtering_prompt_version: int = 1

    # ------------------------------------------------------------ discovery
    job_sources_enabled: str = "remotive,arbeitnow,remoteok,jobicy,greenhouse,lever,ashby,adzuna,jsearch,jooble,email_alerts,ycombinator,himalayas,weworkremotely,hn_hiring"
    job_source_timeout: float = 30.0
    job_source_max_per_source: int = 200
    job_user_agent: str = "job-agent/0.1 (personal job search assistant)"
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""
    adzuna_country: str = "in"
    rapidapi_key: str = ""            # JSearch on RapidAPI (LinkedIn / Indeed / Naukri listings via Google for Jobs)
    jsearch_country: str = "in"
    jooble_api_key: str = ""
    imap_host: str = ""               # job-alert emails (LinkedIn / Naukri / Indeed) read over IMAP
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"
    imap_days: int = 3
    alert_senders: str = "linkedin.com,naukri.com,indeed.com,glassdoor.com,foundit.in,shine.com,instahyre.com,wellfound.com,hirist.com"

    # ------------------------------------------------------------ scheduler
    scheduler_enabled: bool = False
    schedule_cron: str = "0 8 * * *"
    schedule_timezone: str = "Asia/Kolkata"

    # -------------------------------------------------------- notifications
    notification_providers: str = "console"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""
    smtp_use_tls: bool = True
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # -------------------------------------------------------------- browser
    browser_headless: bool = False
    browser_slow_mo_ms: int = 0
    browser_timeout_ms: int = 30000
    browser_keep_open: bool = True

    @field_validator("database_url")
    @classmethod
    def _ensure_sqlite_dir(cls, value: str) -> str:
        """Normalise the database URL.

        * Relative SQLite paths resolve against the project root (not the process cwd).
        * Plain ``postgresql://`` / ``postgres://`` URLs (what Supabase, Neon and Heroku
          hand out) are routed to the psycopg 3 driver that ships in requirements-postgres.txt.
        """
        value = (value or "").strip()
        if value.startswith("postgres://"):
            value = "postgresql://" + value[len("postgres://"):]
        if value.startswith("postgresql://"):
            value = "postgresql+psycopg://" + value[len("postgresql://"):]
        if value.startswith("sqlite:///") and ":memory:" not in value:
            raw = value[len("sqlite:///"):]
            path = Path(raw)
            if not path.is_absolute():
                path = (ROOT_DIR / raw).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            return "sqlite:///" + path.as_posix()
        return value

    # ---------------------------------------------------------- helpers
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def enabled_sources(self) -> list[str]:
        return [s.strip().lower() for s in self.job_sources_enabled.split(",") if s.strip()]

    @property
    def notification_provider_list(self) -> list[str]:
        return [s.strip().lower() for s in self.notification_providers.split(",") if s.strip()]

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def openrouter_configured(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def groq_configured(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def alert_sender_list(self) -> list[str]:
        return [x.strip().lower() for x in self.alert_senders.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Used by tests to re-read environment variables."""
    get_settings.cache_clear()
