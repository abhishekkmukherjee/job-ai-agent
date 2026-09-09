"""Groq - OpenAI-compatible API with a generous free tier and very fast open models."""
from __future__ import annotations

from typing import Any

from .openrouter import OpenRouterProvider


class GroqProvider(OpenRouterProvider):
    name = "groq"
    base_url = "https://api.groq.com/openai/v1"

    def __init__(self, api_key: str, default_model: str, fallback_model: str = "", timeout: float = 60.0, min_interval: float = 2.5):
        super().__init__(
            api_key, default_model, fallback_model, timeout, min_interval, json_mode_supported=True, app_name="job-agent"
        )

    def extra_body(self, model: str) -> dict[str, Any]:
        # gpt-oss / qwen3 are reasoning models: keep thinking short so the JSON answer fits the token budget.
        if "gpt-oss" in model or "qwen3" in model:
            return {"reasoning_effort": "low"}
        return {}
