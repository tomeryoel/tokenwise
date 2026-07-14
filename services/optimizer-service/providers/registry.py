"""Tier-to-provider/model resolution and availability checks."""

import os
from dataclasses import dataclass

import httpx

from providers.ollama_provider import OllamaProvider
from providers.openai_provider import OpenAIProvider

_test_transports: dict[str, httpx.AsyncBaseTransport] = {}


def set_test_transport(provider_name: str, transport: httpx.AsyncBaseTransport) -> None:
    _test_transports[provider_name] = transport


def clear_test_transports() -> None:
    _test_transports.clear()


@dataclass
class ResolvedProvider:
    provider_name: str  # "ollama" or "openai"
    model: str
    executed_tier: str


def _ollama_model_for_tier(tier: str) -> str:
    mapping = {
        "local": os.environ.get("OLLAMA_LOCAL_MODEL", ""),
        "cheap": os.environ.get("OLLAMA_CHEAP_MODEL", ""),
        "balanced": os.environ.get("OLLAMA_BALANCED_MODEL", ""),
        "premium": os.environ.get("OLLAMA_BALANCED_MODEL", ""),  # fallback, not labelled premium
        "fallback": os.environ.get("OLLAMA_BALANCED_MODEL", ""),
    }
    return mapping.get(tier, os.environ.get("OLLAMA_CHEAP_MODEL", ""))


def _openai_model_for_tier(tier: str) -> str:
    mapping = {
        "cheap": os.environ.get("OPENAI_CHEAP_MODEL", ""),
        "balanced": os.environ.get("OPENAI_BALANCED_MODEL", ""),
        "premium": os.environ.get("OPENAI_PREMIUM_MODEL", ""),
        "fallback": os.environ.get("OPENAI_BALANCED_MODEL", ""),
    }
    return mapping.get(tier, "")


def resolve_primary(
    requested_tier: str,
    privacy_enforced: bool,
) -> ResolvedProvider:
    """Resolve the primary provider for a given tier."""
    tier = requested_tier.lower()

    if tier == "local" or privacy_enforced:
        return ResolvedProvider("ollama", _ollama_model_for_tier("local" if tier == "local" else tier), tier if tier == "local" else "local")

    if tier in ("cheap", "balanced", "premium", "fallback"):
        openai = OpenAIProvider()
        if openai.is_configured():
            model = _openai_model_for_tier(tier)
            if model:
                return ResolvedProvider("openai", model, tier)
        # External not available -> Ollama fallback for this tier
        ollama_tier = tier if tier in ("cheap", "balanced") else "balanced"
        return ResolvedProvider("ollama", _ollama_model_for_tier(ollama_tier), ollama_tier)

    if tier == "vision":
        return ResolvedProvider("unsupported", "", "vision")

    return ResolvedProvider("ollama", _ollama_model_for_tier("cheap"), "cheap")


def resolve_fallback(
    fallback_tier: str,
    privacy_enforced: bool,
) -> ResolvedProvider | None:
    """Resolve the fallback provider. Returns None if no fallback is permitted."""
    if not fallback_tier or fallback_tier == "none":
        return None

    tier = fallback_tier.lower()
    if privacy_enforced:
        model = _ollama_model_for_tier(tier if tier in ("local", "cheap", "balanced") else "cheap")
        if model:
            return ResolvedProvider("ollama", model, tier)
        return None

    openai = OpenAIProvider()
    if openai.is_configured() and tier in ("cheap", "balanced", "premium"):
        model = _openai_model_for_tier(tier)
        if model:
            return ResolvedProvider("openai", model, tier)

    model = _ollama_model_for_tier(tier if tier in ("local", "cheap", "balanced", "premium") else "balanced")
    if model:
        return ResolvedProvider("ollama", model, tier)
    return None


def get_provider_instance(name: str, transport: httpx.AsyncBaseTransport | None = None):
    resolved_transport = transport if transport is not None else _test_transports.get(name)
    if name == "ollama":
        return OllamaProvider(transport=resolved_transport)
    if name == "openai":
        return OpenAIProvider(transport=resolved_transport)
    return None
