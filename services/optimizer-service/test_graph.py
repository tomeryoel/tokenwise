"""Unit tests for the LangGraph optimization engine (graph.py).

Run without Docker or a live n8n:

    cd services/optimizer-service
    pip install -r requirements.txt pytest
    python -m pytest -q
"""
from graph import run_optimizer

TIER_ORDER = ["reject", "cache", "local", "cheap", "balanced", "vision", "premium"]


def _run(**kw):
    return run_optimizer(kw)


def test_sensitive_forces_local():
    r = _run(prompt="My email is x@y.com, reset my password",
             policy_mode="balanced", require_local_model=True,
             contains_sensitive_data=True)
    assert r["selected_tier"] == "local"
    assert r["optimization_plan"]["local_only"] is True
    assert r["optimization_plan"]["allow_external"] is False


def test_sensitive_has_no_external_fallback():
    r = _run(prompt="reset my password for account 123",
             policy_mode="aggressive", require_local_model=True,
             contains_sensitive_data=True)
    assert r["fallback_tier"] == "none"
    assert "no external fallback" in r["fallback_reason"]


def test_aggressive_downgrades_eligible_request():
    prompt = "Review this Python function and explain why it leaks memory."
    aggressive = _run(prompt=prompt, policy_mode="aggressive")
    conservative = _run(prompt=prompt, policy_mode="conservative")
    assert TIER_ORDER.index(aggressive["selected_tier"]) < TIER_ORDER.index(
        conservative["selected_tier"]
    )


def test_conservative_protects_quality_on_high_complexity():
    prompt = ("Design and compare two scalable architectures for an enterprise "
              "LLM gateway, including latency, privacy, reliability, failure "
              "modes, and cost tradeoffs.")
    r = _run(prompt=prompt, policy_mode="conservative")
    assert r["complexity_level"] == "high"
    assert r["selected_tier"] == "premium"


def test_high_complexity_can_justify_premium():
    prompt = ("Design and compare two scalable architectures and evaluate the "
              "tradeoffs, failure modes and reliability in depth.")
    r = _run(prompt=prompt, policy_mode="balanced")
    assert r["complexity_level"] == "high"
    assert r["selected_tier"] in {"premium", "balanced"}
    # with high quality requirement it should reach premium
    assert r["quality_requirement"] == "high"
    assert r["selected_tier"] == "premium"


def test_long_prompt_recommends_compression():
    long_prompt = ("TokenWise reduces cost by caching and routing. " * 60)
    r = _run(prompt=long_prompt, policy_mode="aggressive")
    assert r["compression_recommended"] is True
    assert r["compression_target_ratio"] < 1.0


def test_short_prompt_no_compression():
    r = _run(prompt="How do I reset my password?", policy_mode="aggressive")
    assert r["compression_recommended"] is False
    assert r["compression_target_ratio"] == 1.0


def test_savings_never_negative():
    for mode in ("conservative", "balanced", "aggressive"):
        r = _run(prompt="How do I reset my password?", policy_mode=mode)
        assert r["estimated_savings"] >= 0.0
        assert r["estimated_optimized_cost"] <= r["estimated_baseline_cost"]


def test_support_request_classified_low_complexity():
    r = _run(prompt="How do I reset my password?", policy_mode="balanced")
    assert r["task_type"] == "support_request"
    assert r["complexity_level"] == "low"
    assert r["selected_tier"] in {"local", "cheap"}


def test_translation_routes_cheap_or_local():
    r = _run(prompt="Translate this support response into Hebrew: your password "
                    "has been reset successfully.", policy_mode="balanced")
    assert r["task_type"] == "translation"
    assert r["selected_tier"] in {"local", "cheap", "balanced"}


def test_blocked_guardrail_yields_reject_tier():
    r = _run(prompt="anything", policy_mode="balanced", guardrail_status="blocked")
    assert r["selected_tier"] == "reject"


def test_policy_modes_produce_different_plans():
    prompt = "Review this Python function and explain why it leaks memory."
    tiers = {m: _run(prompt=prompt, policy_mode=m)["selected_tier"]
             for m in ("conservative", "balanced", "aggressive")}
    assert len(set(tiers.values())) >= 2
