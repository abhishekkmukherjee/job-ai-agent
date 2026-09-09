"""OpenRouter provider (OpenAI-compatible chat completions)."""
from __future__ import annotations

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

BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(AIProvider):
    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        default_model: str,
        fallback_model: str = "",
        timeout: float = 60.0,
        min_interval: float = 3.0,
        json_mode_supported: bool = False,
        site_url: str = "",
        app_name: str = "job-agent",
    ):
        super().__init__(default_model, fallback_model, timeout, min_interval)
        self.api_key = api_key
        self.json_mode_supported = json_mode_supported
        self.site_url = site_url
        self.app_name = app_name

    def is_configured(self) -> bool:
        return bool(self.api_key and self.default_model)

    async def _complete(
        self, prompt: str, *, system: str | None, model: str, json_mode: bool, temperature: float, max_tokens: int
    ) -> AIResponse:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if json_mode and self.json_mode_supported:
            body["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.site_url or "http://localhost",
            "X-Title": self.app_name,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{BASE_URL}/chat/completions", json=body, headers=headers)
        except httpx.TimeoutException as e:
            raise AITransientError(f"openrouter timeout: {e}") from e
        except httpx.HTTPError as e:
            raise AITransientError(f"openrouter connection error: {e}") from e

        if resp.status_code == 429:
            retry_after = None
            if resp.headers.get("retry-after"):
                try:
                    retry_after = float(resp.headers["retry-after"])
                except ValueError:
                    retry_after = None
            raise AIRateLimitError(f"openrouter rate limited ({model})", retry_after=retry_after)
        if resp.status_code in (401, 403):
            raise AIConfigurationError(f"openrouter auth error: {resp.text[:200]}")
        if resp.status_code in (400, 404):
            raise AIConfigurationError(f"openrouter {resp.status_code} for {model}: {resp.text[:300]}")
        if resp.status_code == 402:
            raise AIError(f"openrouter: insufficient credits for {model}: {resp.text[:200]}")
        if resp.status_code >= 500:
            raise AITransientError(f"openrouter {resp.status_code}: {resp.text[:200]}")
        if resp.status_code != 200:
            raise AIError(f"openrouter unexpected {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        if data.get("error"):
            err = data["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            code = err.get("code") if isinstance(err, dict) else None
            if code == 429 or "rate" in msg.lower():
                raise AIRateLimitError(f"openrouter: {msg}")
            raise AITransientError(f"openrouter error: {msg}")
        choices = data.get("choices") or []
        if not choices:
            raise AIResponseError("openrouter returned no choices")
        message = choices[0].get("message") or {}
        text = message.get("content") or ""
        if isinstance(text, list):
            text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        if not text.strip():
            raise AIResponseError("openrouter returned empty content")
        usage = data.get("usage") or {}
        return AIResponse(
            text=text, provider=self.name, model=data.get("model") or model,
            usage={k: usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")},
        )
