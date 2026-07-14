"""Unit tests for Layer 4 provider adapters (mocked HTTP, no paid API calls).

Run:
    cd services/optimizer-service
    pip install -r requirements.txt
    python -m pytest test_providers.py test_graph.py -q
"""
import json

import httpx
import pytest

from providers.executor import execute_provider
from providers.ollama_provider import OllamaProvider
from providers.openai_provider import OpenAIProvider
from providers.pricing import calculate_cost
from providers.registry import set_test_transport
from providers.schemas import OptimizationPlanInput, ProviderExecuteRequest


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.test:11434")
    monkeypatch.setenv("OLLAMA_LOCAL_MODEL", "llama3.1:latest")
    monkeypatch.setenv("OLLAMA_CHEAP_MODEL", "llama3.1:latest")
    monkeypatch.setenv("OLLAMA_BALANCED_MODEL", "llama3.1:latest")
    monkeypatch.setenv("ENABLE_OPENAI_PROVIDER", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("MODEL_PRICING_CONFIG_PATH", "config/model_pricing.json")

    async def _installed(self, model: str) -> bool:
        return model in ("llama3.1:latest", "missing-model") and model != "missing-model"

    monkeypatch.setattr(OllamaProvider, "is_model_installed", _installed)


def _req(**kw) -> ProviderExecuteRequest:
    defaults = {
        "request_id": "t1",
        "prompt": "How do I reset my password?",
        "selected_tier": "cheap",
        "fallback_tier": "balanced",
        "estimated_baseline_cost": 0.001,
        "estimated_optimized_cost": 0.0001,
        "optimization_plan": OptimizationPlanInput(route="cheap"),
    }
    defaults.update(kw)
    return ProviderExecuteRequest(**defaults)


OLLAMA_CHAT_OK = {
    "message": {"role": "assistant", "content": "Reset your password via Settings."},
    "prompt_eval_count": 18,
    "eval_count": 42,
    "total_duration": 1_200_000_000,
    "load_duration": 100_000_000,
}


def _ollama_ok_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/chat":
        return httpx.Response(200, json=OLLAMA_CHAT_OK)
    return httpx.Response(404)


def _openai_ok_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/responses"):
        return httpx.Response(200, json={
            "id": "resp_abc",
            "output": [{"content": [{"type": "output_text", "text": "Hello from OpenAI."}]}],
            "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        })
    return httpx.Response(404)


# --------------------------------------------------------------------------- #
# Provider adapter tests
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_ollama_response_normalization():
    p = OllamaProvider(transport=httpx.MockTransport(_ollama_ok_handler))
    r = await p.execute("test prompt", "llama3.1:latest")
    assert r.success is True
    assert r.answer == "Reset your password via Settings."
    assert r.actual_input_tokens == 18
    assert r.actual_output_tokens == 42
    assert r.actual_total_tokens == 60
    assert r.provider_total_duration_ms == 1200
    assert r.provider_load_duration_ms == 100


@pytest.mark.asyncio
async def test_ollama_model_not_installed(monkeypatch):
    async def _not_installed(self, model: str) -> bool:
        return False

    monkeypatch.setattr(OllamaProvider, "is_model_installed", _not_installed)
    p = OllamaProvider(transport=httpx.MockTransport(_ollama_ok_handler))
    r = await p.execute("test", "missing-model")
    assert r.success is False
    assert r.error_code == "MODEL_NOT_INSTALLED"


@pytest.mark.asyncio
async def test_openai_disabled_without_credentials():
    p = OpenAIProvider()
    assert p.is_configured() is False
    r = await p.execute("test", "gpt-4o-mini")
    assert r.success is False
    assert r.error_code == "PROVIDER_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_openai_response_normalization(monkeypatch):
    monkeypatch.setenv("ENABLE_OPENAI_PROVIDER", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key-not-real")
    monkeypatch.setenv("OPENAI_CHEAP_MODEL", "gpt-4o-mini")
    p = OpenAIProvider(transport=httpx.MockTransport(_openai_ok_handler))
    r = await p.execute("test", "gpt-4o-mini")
    assert r.success is True
    assert r.answer == "Hello from OpenAI."
    assert r.actual_input_tokens == 10
    assert r.actual_output_tokens == 20


def test_cost_calculation_ollama_zero():
    cost, status = calculate_cost("llama3.1:latest", 100, 50, "ollama")
    assert cost == 0.0
    assert status == "local_zero_api_cost"


def test_unknown_paid_model_pricing_null():
    cost, status = calculate_cost("unknown-paid-model", 100, 50, "openai")
    assert cost is None
    assert status == "pricing_not_configured"


# --------------------------------------------------------------------------- #
# Executor / tier / privacy / fallback tests
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_local_tier_selects_ollama():
    set_test_transport("ollama", httpx.MockTransport(_ollama_ok_handler))
    r = await execute_provider(_req(
        selected_tier="local",
        optimization_plan=OptimizationPlanInput(route="local", local_only=True),
    ))
    assert r.success is True
    assert r.provider == "ollama"
    assert r.executed_tier == "local"


@pytest.mark.asyncio
async def test_sensitive_forces_ollama_even_when_external_enabled(monkeypatch):
    monkeypatch.setenv("ENABLE_OPENAI_PROVIDER", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_CHEAP_MODEL", "gpt-4o-mini")
    set_test_transport("ollama", httpx.MockTransport(_ollama_ok_handler))
    r = await execute_provider(_req(
        selected_tier="cheap",
        require_local_model=True,
        contains_sensitive_data=True,
        optimization_plan=OptimizationPlanInput(route="local", local_only=True, allow_external=False),
    ))
    assert r.success is True
    assert r.provider == "ollama"
    assert r.privacy_enforced is True
    assert all(a.provider != "openai" for a in r.attempts)


@pytest.mark.asyncio
async def test_sensitive_never_external_fallback(monkeypatch):
    monkeypatch.setenv("ENABLE_OPENAI_PROVIDER", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    async def _not_installed(self, model: str) -> bool:
        return False

    monkeypatch.setattr(OllamaProvider, "is_model_installed", _not_installed)
    r = await execute_provider(_req(
        selected_tier="local",
        fallback_tier="balanced",
        require_local_model=True,
        optimization_plan=OptimizationPlanInput(route="local", local_only=True, allow_external=False),
    ))
    assert r.success is False
    assert all(a.provider != "openai" for a in r.attempts)


@pytest.mark.asyncio
async def test_missing_external_triggers_ollama_fallback():
    set_test_transport("ollama", httpx.MockTransport(_ollama_ok_handler))
    r = await execute_provider(_req(selected_tier="cheap"))
    assert r.success is True
    assert r.provider == "ollama"
    assert r.used_fallback is True
    assert r.fallback_reason == "external_provider_not_configured"


@pytest.mark.asyncio
async def test_cheap_tier_uses_openai_when_configured(monkeypatch):
    monkeypatch.setenv("ENABLE_OPENAI_PROVIDER", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_CHEAP_MODEL", "gpt-4o-mini")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "output": [{"content": [{"type": "output_text", "text": "OpenAI answer."}]}],
            "usage": {"input_tokens": 5, "output_tokens": 10},
        })

    set_test_transport("openai", httpx.MockTransport(handler))
    r = await execute_provider(_req(selected_tier="cheap"))
    assert r.success is True
    assert r.provider == "openai"
    assert r.used_fallback is False


@pytest.mark.asyncio
async def test_timeout_triggers_one_fallback():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.TimeoutException("timeout")
        return httpx.Response(200, json=OLLAMA_CHAT_OK)

    set_test_transport("ollama", httpx.MockTransport(handler))
    r = await execute_provider(_req(selected_tier="cheap", fallback_tier="balanced"))
    assert r.success is True
    assert len(r.attempts) == 3
    assert r.attempts[0].provider == "openai"
    assert r.attempts[0].success is False
    assert r.used_fallback is True


@pytest.mark.asyncio
async def test_both_attempts_fail():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "server error"})

    set_test_transport("ollama", httpx.MockTransport(handler))
    r = await execute_provider(_req(selected_tier="cheap", fallback_tier="balanced"))
    assert r.success is False
    assert r.error_code == "ALL_ATTEMPTS_FAILED"
    assert len(r.attempts) == 3
    assert r.attempts[0].provider == "openai"


@pytest.mark.asyncio
async def test_cache_tier_does_not_execute():
    r = await execute_provider(_req(selected_tier="cache"))
    assert r.success is False
    assert r.error_code == "EXECUTION_NOT_REQUIRED"


@pytest.mark.asyncio
async def test_reject_tier_does_not_execute():
    r = await execute_provider(_req(selected_tier="reject"))
    assert r.success is False
    assert r.error_code == "REQUEST_REJECTED"


@pytest.mark.asyncio
async def test_no_api_keys_in_error_response(monkeypatch):
    monkeypatch.setenv("ENABLE_OPENAI_PROVIDER", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-key-12345")

    def openai_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid key"})

    def ollama_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "server error"})

    set_test_transport("openai", httpx.MockTransport(openai_handler))
    set_test_transport("ollama", httpx.MockTransport(ollama_handler))
    r = await execute_provider(_req(selected_tier="cheap", fallback_tier="none"))
    dumped = json.dumps(r.model_dump())
    assert "sk-super-secret" not in dumped
    assert "OPENAI_API_KEY" not in dumped
