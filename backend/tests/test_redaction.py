"""Secrets never reach the database, the tracker or the logs; pasted secrets are cleaned up.

Background: GitHub Actions secrets saved with a trailing newline made every provider call
fail with httpx's "Illegal header value b'Bearer <key>\\n'", and that message - key included -
was stored verbatim in pipeline_failures.
"""
import httpx
import pytest

from app.ai.base import AITransientError
from app.ai.openrouter import OpenRouterProvider
from app.config import Settings
from app.logging_config import redact

GROQ = "gsk_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8s9T0"
GEMINI = "AQ." + "Ab8RN6KP2X1onUNOzBCCDogXu-lDVlB9y6piMLaF"
TELEGRAM = "8812705931:" + "AAFU4sGD1XAy-hiKYxNvXdhZ5hXm_pm-e1oXYZ"


def test_string_settings_are_stripped_of_surrounding_whitespace():
    s = Settings(_env_file=None, gemini_api_key=f"{GEMINI}\n", groq_api_key=f" {GROQ} ", smtp_host="smtp.gmail.com\r\n")
    assert s.gemini_api_key == GEMINI
    assert s.groq_api_key == GROQ
    assert s.smtp_host == "smtp.gmail.com"


def test_settings_read_from_environment_are_stripped(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", f"{GROQ}\n")
    monkeypatch.setenv("API_PORT", " 8010 ")
    s = Settings(_env_file=None)
    assert s.groq_api_key == GROQ
    assert s.api_port == 8010


def test_httpx_illegal_header_message_is_redacted():
    out = redact(f"groq connection error: Illegal header value b'Bearer {GROQ}\\n'")
    assert GROQ not in out
    assert "groq connection error" in out


def test_bare_keys_and_telegram_tokens_are_redacted():
    out = redact(f"gemini {GEMINI} groq {GROQ} telegram {TELEGRAM}")
    assert GEMINI not in out
    assert GROQ not in out
    assert TELEGRAM not in out


async def test_provider_transport_error_never_contains_the_api_key(monkeypatch):
    key = f"{GROQ}\n"
    provider = OpenRouterProvider(api_key=key, default_model="m", min_interval=0)

    async def boom(self, *args, **kwargs):
        raise httpx.LocalProtocolError(f"Illegal header value b'Bearer {key}'")

    monkeypatch.setattr(httpx.AsyncClient, "post", boom)
    with pytest.raises(AITransientError) as info:
        await provider.complete("hi", model="m")
    assert GROQ not in str(info.value)
    assert "connection error" in str(info.value)
