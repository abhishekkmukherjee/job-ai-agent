"""Provider-agnostic AI interfaces."""
from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class AIError(Exception):
    """Base class for provider errors.  Permanent unless a subclass says otherwise."""


class AIConfigurationError(AIError):
    """Missing API key / bad model name - do not retry."""


class AIRateLimitError(AIError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class AITransientError(AIError):
    """Timeouts, connection errors, 5xx - safe to retry."""


class AIResponseError(AIError):
    """Empty / blocked / unparsable response."""


class AIUnavailableError(AIError):
    """Every provider in the chain failed."""

    def __init__(self, task: str, errors: list[str]):
        self.task = task
        self.errors = errors
        super().__init__(f"All AI providers failed for task '{task}': " + " | ".join(errors[-4:]))


@dataclass
class AIResponse:
    text: str
    provider: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    raw: Any = None


class AIProvider(ABC):
    """A chat/completion backend.

    Subclasses implement `_complete`.  The base class adds a simple per-provider
    request throttle so free-tier rate limits are respected proactively.
    """

    name: str = "base"

    def __init__(self, default_model: str, fallback_model: str = "", timeout: float = 60.0, min_interval: float = 0.0):
        self.default_model = default_model
        self.fallback_model = fallback_model
        self.timeout = timeout
        self.min_interval = min_interval
        self._last_request_at = 0.0
        self._lock = asyncio.Lock()
        self.cooldown_until = 0.0   # monotonic timestamp; while in the future the provider is skipped
        self.cooldown_reason = ""

    # ---------------------------------------------------------- cooldown
    def start_cooldown(self, seconds: float, reason: str = "rate limited") -> None:
        self.cooldown_until = max(self.cooldown_until, time.monotonic() + max(1.0, seconds))
        self.cooldown_reason = reason

    def in_cooldown(self) -> bool:
        return time.monotonic() < self.cooldown_until

    def cooldown_remaining(self) -> float:
        return max(0.0, self.cooldown_until - time.monotonic())

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    async def _complete(
        self, prompt: str, *, system: str | None, model: str, json_mode: bool, temperature: float, max_tokens: int
    ) -> AIResponse: ...

    def models(self) -> list[str]:
        return [m for m in [self.default_model, self.fallback_model] if m]

    async def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            wait = self._last_request_at + self.min_interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        json_mode: bool = True,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> AIResponse:
        if not self.is_configured():
            raise AIConfigurationError(f"{self.name} provider is not configured")
        await self._throttle()
        started = time.perf_counter()
        response = await self._complete(
            prompt, system=system, model=model or self.default_model, json_mode=json_mode,
            temperature=temperature, max_tokens=max_tokens,
        )
        response.latency_ms = int((time.perf_counter() - started) * 1000)
        if not response.text or not response.text.strip():
            raise AIResponseError(f"{self.name} returned an empty response")
        return response

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name, "configured": self.is_configured(), "models": self.models(),
            "cooldown_seconds": int(self.cooldown_remaining()), "cooldown_reason": self.cooldown_reason if self.in_cooldown() else "",
        }
