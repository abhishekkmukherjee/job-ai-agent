"""Model routing with fallback and bounded exponential backoff.

    Simple extraction/classification -> cheap provider (OpenRouter free model)
    Complex matching / generation    -> strong provider (Gemini)
    Fallback                         -> OpenRouter

Chains are configured through AI_ROUTE_* environment variables.  Every call
ends in either a schema-validated Pydantic object or `AIUnavailableError` -
there are no infinite retry loops.
"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from ..config import Settings
from ..logging_config import log_event
from .base import (
    AIConfigurationError,
    AIError,
    AIProvider,
    AIRateLimitError,
    AIResponseError,
    AITransientError,
    AIUnavailableError,
)
from .json_utils import extract_json

T = TypeVar("T", bound=BaseModel)

TASKS = ("classification", "job_analysis", "resume_tailoring", "application_questions")
JSON_NUDGE = "\n\nIMPORTANT: Respond with ONLY a single valid JSON object. No markdown, no commentary."


@dataclass
class AIMeta:
    provider: str
    model: str
    usage: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0
    attempts: int = 1


def parse_chain(spec: str) -> list[tuple[str, str | None]]:
    chain: list[tuple[str, str | None]] = []
    for entry in (spec or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            provider, model = entry.split(":", 1)
            chain.append((provider.strip().lower(), model.strip() or None))
        else:
            chain.append((entry.lower(), None))
    return chain


class AIRouter:
    def __init__(self, providers: dict[str, AIProvider], settings: Settings):
        self.providers = providers
        self.settings = settings
        self.max_retries = max(1, settings.ai_max_retries)
        self.backoff_base = settings.ai_backoff_base
        self.backoff_max = settings.ai_backoff_max
        fallback = parse_chain(settings.ai_route_fallback)
        self.routes: dict[str, list[tuple[str, str | None]]] = {
            "classification": parse_chain(settings.ai_route_classification),
            "job_analysis": parse_chain(settings.ai_route_job_analysis),
            "resume_tailoring": parse_chain(settings.ai_route_resume_tailoring),
            "application_questions": parse_chain(settings.ai_route_application_questions),
        }
        for chain in self.routes.values():
            for entry in fallback:
                if entry not in chain:
                    chain.append(entry)
        self.stats: dict[str, int] = {"requests": 0, "failures": 0, "rate_limits": 0}

    # ------------------------------------------------------------ helpers
    def configured_providers(self) -> list[str]:
        return [name for name, p in self.providers.items() if p.is_configured()]

    def is_available(self) -> bool:
        return bool(self.configured_providers())

    def _chain_for(self, task: str) -> list[tuple[AIProvider, str | None]]:
        out: list[tuple[AIProvider, str | None]] = []
        for name, model in self.routes.get(task, []):
            provider = self.providers.get(name)
            if provider is not None and provider.is_configured():
                out.append((provider, model))
        return out

    def _backoff(self, attempt: int, retry_after: float | None = None) -> float:
        if retry_after:
            return min(self.backoff_max, retry_after + random.uniform(0, 1))
        return min(self.backoff_max, self.backoff_base * (2**attempt) + random.uniform(0, 0.5))

    # -------------------------------------------------------------- calls
    async def complete_json(
        self,
        task: str,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> tuple[T, AIMeta]:
        chain = self._chain_for(task)
        if not chain:
            raise AIUnavailableError(task, ["no AI provider configured (set GEMINI_API_KEY or OPENROUTER_API_KEY)"])
        errors: list[str] = []
        total_attempts = 0
        for provider, model in chain:
            models = [model] if model else provider.models()
            for model_name in models:
                nudged = False
                for attempt in range(self.max_retries):
                    total_attempts += 1
                    self.stats["requests"] += 1
                    current_prompt = prompt + (JSON_NUDGE if nudged else "")
                    try:
                        response = await provider.complete(
                            current_prompt, system=system, model=model_name, json_mode=True,
                            temperature=temperature, max_tokens=max_tokens,
                        )
                        data = extract_json(response.text)
                        obj = schema.model_validate(data)
                        log_event(
                            "AI_REQUEST", task=task, provider=provider.name, model=response.model,
                            latency_ms=response.latency_ms, tokens=response.usage.get("total_tokens"), attempt=attempt + 1,
                        )
                        return obj, AIMeta(provider.name, response.model, response.usage, response.latency_ms, total_attempts)
                    except AIRateLimitError as e:
                        self.stats["rate_limits"] += 1
                        errors.append(f"{provider.name}/{model_name}: {e}")
                        if attempt < self.max_retries - 1:
                            await asyncio.sleep(self._backoff(attempt, e.retry_after))
                            continue
                        break  # next model / provider
                    except AITransientError as e:
                        errors.append(f"{provider.name}/{model_name}: {e}")
                        if attempt < self.max_retries - 1:
                            await asyncio.sleep(self._backoff(attempt))
                            continue
                        break
                    except (AIResponseError, ValueError, ValidationError) as e:
                        msg = str(e).replace("\n", " ")[:200]
                        errors.append(f"{provider.name}/{model_name}: invalid response: {msg}")
                        if not nudged and attempt < self.max_retries - 1:
                            nudged = True
                            continue
                        break
                    except AIConfigurationError as e:
                        errors.append(f"{provider.name}/{model_name}: {e}")
                        break  # try the next model / provider, never retry
                    except AIError as e:
                        errors.append(f"{provider.name}/{model_name}: {e}")
                        break
        self.stats["failures"] += 1
        log_event("AI_REQUEST_FAILED", task=task, errors=errors[-3:], level=logging.WARNING)
        raise AIUnavailableError(task, errors)

    # ------------------------------------------------------------- status
    def status_summary(self) -> dict[str, Any]:
        return {
            "configured_providers": self.configured_providers(),
            "providers": {name: p.describe() for name, p in self.providers.items()},
            "routes": {task: [f"{n}:{m}" if m else n for n, m in chain] for task, chain in self.routes.items()},
            "stats": dict(self.stats),
        }

    async def self_test(self) -> dict[str, Any]:
        """Send a tiny JSON request to every configured provider."""

        class Ping(BaseModel):
            ok: bool

        results: dict[str, Any] = {}
        for name, provider in self.providers.items():
            if not provider.is_configured():
                results[name] = {"ok": False, "error": "not configured"}
                continue
            try:
                resp = await provider.complete('Reply with exactly this JSON: {"ok": true}', json_mode=True, max_tokens=64)
                Ping.model_validate(extract_json(resp.text))
                results[name] = {"ok": True, "model": resp.model, "latency_ms": resp.latency_ms}
            except Exception as e:  # noqa: BLE001 - report every failure kind
                results[name] = {"ok": False, "error": str(e)[:300]}
        return results
