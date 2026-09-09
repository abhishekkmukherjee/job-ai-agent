"""Structured logging.

Every important pipeline step emits an *event* (JOB_DISCOVERED, AI_ANALYSIS_STARTED, ...)
through `log_event`.  Records are rendered either as JSON (production) or as a readable
line (development).  A redaction filter guarantees that API keys, tokens, cookies and
passwords never reach the log output.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

SENSITIVE_KEY_PATTERN = re.compile(
    r"(api[_-]?key|authorization|token|secret|password|passwd|cookie|session_id)", re.IGNORECASE
)
# Long opaque strings that look like credentials (e.g. "AIzaSy..." or "sk-or-v1-...")
SENSITIVE_VALUE_PATTERN = re.compile(
    r"(AIza[0-9A-Za-z\-_]{20,}|sk-or-v1-[0-9a-f]{20,}|sk-[A-Za-z0-9]{20,}|Bearer\s+\S+)"
)

EVENTS = {
    "JOB_DISCOVERED",
    "JOB_DUPLICATE",
    "JOB_FILTERED",
    "JOB_PASSED_FILTER",
    "AI_ANALYSIS_STARTED",
    "AI_ANALYSIS_COMPLETED",
    "AI_ANALYSIS_FAILED",
    "AI_CACHE_HIT",
    "AI_REQUEST",
    "AI_REQUEST_FAILED",
    "APPLICATION_STARTED",
    "APPLICATION_PREPARED",
    "APPLICATION_FILLED",
    "APPLICATION_FAILED",
    "SEARCH_RUN_STARTED",
    "SEARCH_RUN_COMPLETED",
    "SOURCE_FETCHED",
    "SOURCE_FAILED",
    "NOTIFICATION_SENT",
    "NOTIFICATION_FAILED",
    "SCHEDULER_STARTED",
}


def redact(value: Any) -> Any:
    """Recursively redact anything that looks like a credential."""
    if isinstance(value, dict):
        return {
            k: ("***REDACTED***" if SENSITIVE_KEY_PATTERN.search(str(k)) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return SENSITIVE_VALUE_PATTERN.sub("***REDACTED***", value)
    return value


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = SENSITIVE_VALUE_PATTERN.sub("***REDACTED***", record.msg)
        if hasattr(record, "event_data"):
            record.event_data = redact(record.event_data)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "event"):
            payload["event"] = record.event
        if hasattr(record, "event_data"):
            payload.update(record.event_data)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.now().strftime("%H:%M:%S")
        if hasattr(record, "event"):
            base = f"{ts} {record.levelname:<7} [{record.event}] {record.getMessage()}"
        else:
            base = f"{ts} {record.levelname:<7} {record.name}: {record.getMessage()}"
        if getattr(record, "event_data", None):
            extras = " ".join(f"{k}={json.dumps(v, default=str)}" for k, v in record.event_data.items())
            base = f"{base} {extras}"
        if record.exc_info:
            base = f"{base}\n{self.formatException(record.exc_info)}"
        return base


def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    handler.addFilter(RedactionFilter())
    root.addHandler(handler)
    for noisy in ("httpx", "httpcore", "apscheduler", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def log_event(event: str, message: str = "", level: int = logging.INFO, **data: Any) -> None:
    """Emit a structured pipeline event."""
    logger = logging.getLogger("job_agent")
    logger.log(level, message or event, extra={"event": event, "event_data": redact(data)})


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
