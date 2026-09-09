"""Google Gemini provider (REST API via httpx - no heavy SDK dependency)."""
from __future__ import annotations

import re
from typing import Any

import httpx

from .base import (
    AIConfigurationError,
    AIError,
    AIProvider,
    AIRateLimitError,
    AIResponse,
    AIResponseError,
    AITransientError,
)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_RETRY_DELAY_RE = re.compile(r"retry in ([0-9.]+)s|retryDelay\"?:\s*\"?([0-9.]+)s", re.IGNORECASE)


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(
        self,
        api_key: str,
        default_model: str = "gemini-2.5-flash",
        fallback_model: str = "gemini-2.0-flash",
        timeout: float = 60.0,
        min_interval: float = 4.0,
        thinking_budget: int | None = None,
    ):
        super().__init__(default_model, fallback_model, timeout, min_interval)
        self.api_key = api_key
        self.thinking_budget = thinking_budget

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def _complete(
        self, prompt: str, *, system: str | None, model: str, json_mode: bool, temperature: float, max_tokens: int
    ) -> AIResponse:
        url = f"{BASE_URL}/models/{model}:generateContent"
        generation_config: dict[str, Any] = {"temperature": temperature, "maxOutputTokens": max_tokens}
        if json_mode:
            generation_config["responseMimeType"] = "application/json"
        if self.thinking_budget is not None and "2.5" in model:
            generation_config["thinkingConfig"] = {"thinkingBudget": self.thinking_budget}
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as e:
            raise AITransientError(f"gemini timeout: {e}") from e
        except httpx.HTTPError as e:
            raise AITransientError(f"gemini connection error: {e}") from e

        if resp.status_code == 429:
            retry_after = None
            m = _RETRY_DELAY_RE.search(resp.text)
            if m:
                retry_after = float(m.group(1) or m.group(2))
            elif resp.headers.get("retry-after"):
                try:
                    retry_after = float(resp.headers["retry-after"])
                except ValueError:
                    retry_after = None
            raise AIRateLimitError(f"gemini rate limited ({model})", retry_after=retry_after)
        if resp.status_code in (400, 401, 403, 404):
            raise AIConfigurationError(f"gemini {resp.status_code} for {model}: {resp.text[:300]}")
        if resp.status_code >= 500:
            raise AITransientError(f"gemini {resp.status_code}: {resp.text[:200]}")
        if resp.status_code != 200:
            raise AIError(f"gemini unexpected {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        feedback = data.get("promptFeedback") or {}
        if feedback.get("blockReason"):
            raise AIResponseError(f"gemini blocked prompt: {feedback['blockReason']}")
        candidates = data.get("candidates") or []
        if not candidates:
            raise AIResponseError("gemini returned no candidates")
        cand = candidates[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        finish = cand.get("finishReason", "")
        if not text.strip():
            raise AIResponseError(f"gemini returned empty content (finishReason={finish})")
        if finish == "MAX_TOKENS":
            raise AIResponseError("gemini hit MAX_TOKENS before finishing the response")
        usage_meta = data.get("usageMetadata") or {}
        usage = {
            "prompt_tokens": usage_meta.get("promptTokenCount"),
            "completion_tokens": usage_meta.get("candidatesTokenCount"),
            "total_tokens": usage_meta.get("totalTokenCount"),
        }
        return AIResponse(text=text, provider=self.name, model=model, usage=usage, raw=None)
