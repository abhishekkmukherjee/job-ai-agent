"""Deterministic fake provider for tests and offline development."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from .base import AIProvider, AIResponse


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, responder: Callable[[str, str | None], Any] | None = None, model: str = "fake-model"):
        super().__init__(default_model=model, fallback_model="", timeout=1.0, min_interval=0.0)
        self.responder = responder
        self.calls: list[dict[str, Any]] = []

    def is_configured(self) -> bool:
        return True

    async def _complete(
        self, prompt: str, *, system: str | None, model: str, json_mode: bool, temperature: float, max_tokens: int
    ) -> AIResponse:
        self.calls.append({"prompt": prompt, "system": system, "model": model})
        result = self.responder(prompt, system) if self.responder else {}
        if isinstance(result, Exception):
            raise result
        text = result if isinstance(result, str) else json.dumps(result)
        return AIResponse(text=text, provider=self.name, model=model, usage={"total_tokens": len(prompt) // 4})
