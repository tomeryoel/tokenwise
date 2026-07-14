"""Unit tests for the conditional LangGraph optimization engine (graph.py).

Run without Docker or a live n8n:

    cd services/optimizer-service
    pip install -r requirements.txt pytest
    python -m pytest -q
"""
from graph import run_optimizer

TIER_ORDER = ["reject", "cache", "local", "cheap", "balanced", "vision", "premium"]

# Nodes that only belong to the standard optimization path.
STANDARD_ONLY_NODES = {
    "apply_policy_mode", "decide_compression", "skip_compression",
    "select_model_tier", "build_fallback_plan",
}


def _run(**kw):
    return run_optimizer(kw)


# --------------------------------------------------------------------------- #
# Conditional-path tests (Day 5.1)
# --------------------------------------------------------------------------- #
def test_A_blocked_takes_reject_path():
    r = _run(prompt="anything", policy_mode="balanced", guardrail_status="blocked")
    assert r["graph_path"] == "reject_path"
    assert r["selected_tier"] == "reject"
    # standard policy/compression/tier nodes must NOT execute
    assert STANDARD_ONLY_NODES.isdisjoint(r["executed_nodes"])
    assert "reject_path" in r["executed_nodes"]


def test_B_cache_hit_takes_cache_path():
    r = _run(prompt="repeat", policy_mode="balanced",
             cache_status="hit", cache_confidence=0.95)
    assert r["graph_path"] == "cache_path"
    assert r["selected_tier"] == "cache"
    assert STANDARD_ONLY_NODES.isdisjoint(r["executed_nodes"])
    assert r["estimated_optimized_cost"] == 0.0


def test_C_sensitive_takes_local_only_path():
    r = _run(prompt="My email is x@y.com, reset my password",
             policy_mode="balanced", require_local_model=True,
             contains_sensitive_data=True)
    assert r["graph_path"] == "local_only_path"
    assert r["selected_tier"] == "local"
    assert r["optimization_plan"]["local_only"] is True
    assert r["optimization_plan"]["allow_external"] is False
    assert r["fallback_tier"] == "none"
    # standard tier selection must not run / override
    assert "select_model_tier" not in r["executed_nodes"]


def test_D_image_takes_vision_path():
    r = _run(prompt="What is in this screenshot?", policy_mode="balanced",
             has_image=True, image_complexity=0.8)
    assert r["graph_path"] == "vision_path"
    assert r["selected_tier"] == "vision"
    assert r["fallback_tier"] == "premium"
    assert STANDARD_ONLY_NODES.isdisjoint(r["executed_nodes"])


def test_E_standard_short_skips_compression():
    r = _run(prompt="How do I reset my password?", policy_mode="aggressive")
    assert r["graph_path"] == "standard_optimization_path"
    assert "skip_compression" in r["executed_nodes"]
    assert "decide_compression" not in r["executed_nodes"]
    assert r["compression_recommended"] is False
    assert r["compression_target_ratio"] == 1.0


def test_F_standard_long_aggressive_runs_compression():
    long_prompt = ("TokenWise reduces cost by caching and routing. " * 60)
    r = _run(prompt=long_prompt, policy_mode="aggressive")
    assert r["graph_path"] == "standard_optimization_path"
    assert "decide_compression" in r["executed_nodes"]
    assert "skip_compression" not in r["executed_nodes"]
    assert r["compression_recommended"] is True
    assert r["compression_target_ratio"] < 1.0


def test_G_standard_long_conservative_differs_from_aggressive():
    long_prompt = ("TokenWise reduces cost by caching and routing for support. " * 18)
    aggressive = _run(prompt=long_prompt, policy_mode="aggressive")
    conservative = _run(prompt=long_prompt, policy_mode="conservative")
    assert conservative["graph_path"] == "standard_optimization_path"
    # aggressive recommends compression at this length; conservative does not
    assert aggressive["compression_recommended"] is True
    assert conservative["compression_recommended"] is False
    assert "decide_compression" not in conservative["executed_nodes"]


def test_H_executed_nodes_reflect_actual_run():
    r = _run(prompt="How do I reset my password?", policy_mode="balanced")
    nodes = r["executed_nodes"]
    # shared prefix + router + standard path present
    for n in ["normalize_inputs", "classify_task", "estimate_complexity",
              "evaluate_sensitivity", "evaluate_cache_signal", "route_request_path",
              "apply_policy_mode", "select_model_tier", "build_fallback_plan",
              "calculate_estimated_savings", "build_optimization_plan"]:
        assert n in nodes
    # branches not taken must be absent
    for n in ["reject_path", "cache_path", "local_only_path", "vision_path",
              "decide_compression"]:
        assert n not in nodes


# --------------------------------------------------------------------------- #
# Preserved behavior from Day 5
# --------------------------------------------------------------------------- #
def test_sensitive_has_no_external_fallback():
    r = _run(prompt="reset my password for account 123", policy_mode="aggressive",
             require_local_model=True, contains_sensitive_data=True)
    assert r["fallback_tier"] == "none"


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
    assert r["quality_requirement"] == "high"
    assert r["selected_tier"] == "premium"


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


def test_policy_modes_produce_different_plans():
    prompt = "Review this Python function and explain why it leaks memory."
    tiers = {m: _run(prompt=prompt, policy_mode=m)["selected_tier"]
             for m in ("conservative", "balanced", "aggressive")}
    assert len(set(tiers.values())) >= 2
