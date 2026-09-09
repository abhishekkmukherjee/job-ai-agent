"""Build the provider set + router from settings."""
from __future__ import annotations

from ..config import Settings
from .base import AIProvider
from .gemini import GeminiProvider
from .openrouter import OpenRouterProvider
from .router import AIRouter


def build_providers(settings: Settings) -> dict[str, AIProvider]:
    return {
        "gemini": GeminiProvider(
            api_key=settings.gemini_api_key,
            default_model=settings.gemini_model,
            fallback_model=settings.gemini_fallback_model,
            timeout=settings.ai_request_timeout,
            min_interval=settings.gemini_min_interval,
            thinking_budget=settings.gemini_thinking_budget,
        ),
        "openrouter": OpenRouterProvider(
            api_key=settings.openrouter_api_key,
            default_model=settings.openrouter_model,
            fallback_model=settings.openrouter_fallback_model,
            timeout=settings.ai_request_timeout,
            min_interval=settings.openrouter_min_interval,
            json_mode_supported=settings.openrouter_json_mode,
            site_url=settings.openrouter_site_url,
            app_name=settings.openrouter_app_name,
        ),
    }


def build_ai_router(settings: Settings, providers: dict[str, AIProvider] | None = None) -> AIRouter:
    return AIRouter(providers or build_providers(settings), settings)
