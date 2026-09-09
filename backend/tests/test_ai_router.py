import pytest
from pydantic import BaseModel

from app.ai.base import AIConfigurationError, AIRateLimitError, AITransientError, AIUnavailableError
from app.ai.fake import FakeProvider
from app.ai.router import AIRouter, parse_chain
from app.config import Settings


class Out(BaseModel):
    value: int


def make_settings(**overrides) -> Settings:
    base = dict(
        ai_backoff_base=0.001, ai_backoff_max=0.002, ai_max_retries=3,
        ai_route_classification="cheap,strong", ai_route_job_analysis="strong,cheap",
        ai_route_resume_tailoring="strong", ai_route_application_questions="strong", ai_route_fallback="cheap",
    )
    base.update(overrides)
    return Settings(**base)


def test_parse_chain():
    assert parse_chain("gemini, openrouter:foo/bar:free ,") == [("gemini", None), ("openrouter", "foo/bar:free")]


async def test_router_uses_first_provider_when_ok():
    strong = FakeProvider(lambda p, s: {"value": 1})
    cheap = FakeProvider(lambda p, s: {"value": 2})
    router = AIRouter({"strong": strong, "cheap": cheap}, make_settings())
    out, meta = await router.complete_json("job_analysis", "hi", Out)
    assert out.value == 1 and meta.provider == "fake"
    assert len(strong.calls) == 1 and len(cheap.calls) == 0


async def test_router_falls_back_after_rate_limit():
    strong = FakeProvider(lambda p, s: AIRateLimitError("slow down", retry_after=0.001))
    cheap = FakeProvider(lambda p, s: {"value": 2})
    router = AIRouter({"strong": strong, "cheap": cheap}, make_settings())
    out, meta = await router.complete_json("job_analysis", "hi", Out)
    assert out.value == 2
    assert len(strong.calls) == 3  # bounded retries with backoff, then fallback
    assert router.stats["rate_limits"] == 3


async def test_router_retries_transient_then_succeeds():
    calls = {"n": 0}

    def flaky(p, s):
        calls["n"] += 1
        return AITransientError("503") if calls["n"] < 3 else {"value": 7}

    router = AIRouter({"strong": FakeProvider(flaky), "cheap": FakeProvider(lambda p, s: {"value": 0})}, make_settings())
    out, meta = await router.complete_json("job_analysis", "hi", Out)
    assert out.value == 7 and meta.attempts == 3


async def test_router_nudges_on_invalid_json_then_gives_up_to_next_provider():
    strong = FakeProvider(lambda p, s: "I cannot produce JSON, sorry")
    cheap = FakeProvider(lambda p, s: 'Here: {"value": 5}')
    router = AIRouter({"strong": strong, "cheap": cheap}, make_settings())
    out, _ = await router.complete_json("job_analysis", "hi", Out)
    assert out.value == 5
    assert len(strong.calls) == 2
    assert "ONLY a single valid JSON" in strong.calls[1]["prompt"]


async def test_router_schema_validation_failure_moves_on():
    strong = FakeProvider(lambda p, s: {"value": "not-an-int"})
    cheap = FakeProvider(lambda p, s: {"value": 3})
    router = AIRouter({"strong": strong, "cheap": cheap}, make_settings())
    out, _ = await router.complete_json("job_analysis", "hi", Out)
    assert out.value == 3


async def test_router_configuration_error_is_not_retried():
    strong = FakeProvider(lambda p, s: AIConfigurationError("bad model"))
    cheap = FakeProvider(lambda p, s: {"value": 9})
    router = AIRouter({"strong": strong, "cheap": cheap}, make_settings())
    out, _ = await router.complete_json("job_analysis", "hi", Out)
    assert out.value == 9 and len(strong.calls) == 1


async def test_router_raises_when_everything_fails():
    router = AIRouter(
        {"strong": FakeProvider(lambda p, s: AITransientError("down")), "cheap": FakeProvider(lambda p, s: "garbage")},
        make_settings(),
    )
    with pytest.raises(AIUnavailableError) as exc:
        await router.complete_json("job_analysis", "hi", Out)
    assert "down" in str(exc.value) and router.stats["failures"] == 1


async def test_router_without_configured_providers():
    router = AIRouter({}, make_settings())
    with pytest.raises(AIUnavailableError):
        await router.complete_json("classification", "hi", Out)
    assert router.is_available() is False


def test_factory_builds_all_providers():
    from app.ai.factory import build_ai_router

    router = build_ai_router(make_settings(gemini_api_key="", openrouter_api_key="", groq_api_key="g"))
    assert set(router.providers) == {"gemini", "openrouter", "groq"}
    assert router.configured_providers() == ["groq"]
    assert router.providers["groq"].base_url.startswith("https://api.groq.com")
