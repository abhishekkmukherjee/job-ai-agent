"""Real provider round-trips.  Skipped unless the corresponding API key is set.

Run with:  GEMINI_API_KEY=... pytest -m integration tests/test_providers_integration.py
"""
import os

import pytest
from pydantic import BaseModel

from app.ai.gemini import GeminiProvider
from app.ai.json_utils import extract_json
from app.ai.openrouter import OpenRouterProvider


class Ping(BaseModel):
    ok: bool
    number: int


PROMPT = 'Return exactly this JSON and nothing else: {"ok": true, "number": 42}'


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="GEMINI_API_KEY not set")
async def test_gemini_roundtrip():
    provider = GeminiProvider(os.environ["GEMINI_API_KEY"], default_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"), min_interval=0)
    resp = await provider.complete(PROMPT, json_mode=True, max_tokens=256)
    assert Ping.model_validate(extract_json(resp.text)).number == 42
    assert resp.provider == "gemini"


@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("OPENROUTER_API_KEY"), reason="OPENROUTER_API_KEY not set")
async def test_openrouter_roundtrip():
    provider = OpenRouterProvider(
        os.environ["OPENROUTER_API_KEY"], default_model=os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"), min_interval=0
    )
    resp = await provider.complete(PROMPT, json_mode=True, max_tokens=256)
    assert Ping.model_validate(extract_json(resp.text)).number == 42
