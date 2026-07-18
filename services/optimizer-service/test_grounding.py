"""Focused tests for TokenWise product-question grounding."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from providers.grounding import (
    ALLOWED_RUNTIME_FACT_KEYS,
    build_grounded_system_prompt,
    compact_runtime_facts,
    is_tokenwise_product_question,
    load_capabilities,
    resolve_system_prompt,
)

CAP_PATH = Path(__file__).resolve().parent / "config" / "tokenwise_capabilities.json"


def test_capabilities_schema_has_three_lists():
    caps = load_capabilities(str(CAP_PATH))
    assert caps["version"]
    for key in ("implemented", "partial_or_planned", "unsupported"):
        assert isinstance(caps[key], list) and len(caps[key]) >= 3


def test_implemented_planned_unsupported_separation():
    caps = load_capabilities(str(CAP_PATH))
    impl = " ".join(caps["implemented"]).lower()
    planned = " ".join(caps["partial_or_planned"]).lower()
    unsupported = " ".join(caps["unsupported"]).lower()
    assert "langgraph" in impl or "rule-based" in impl
    assert "semantic cache" in impl
    assert "policy evidence" in planned or "policy intelligence" in planned
    assert "system-load" in unsupported or "system load" in unsupported
    assert "learned routing" in unsupported
    # No overlap of unsupported phrases into implemented list
    assert "real-time system-load" not in impl
    assert "learned routing" not in impl


@pytest.mark.parametrize(
    "prompt",
    [
        "Explain how TokenWise chooses between a local model and an external model.",
        "How does TokenWise choose a model?",
        "Does TokenWise use system load?",
        "Does TokenWise have Policy RAG?",
        "How does TokenWise fallback work?",
        "What is currently implemented in TokenWise?",
        "Which signals affect TokenWise routing?",
    ],
)
def test_detects_tokenwise_product_questions(prompt):
    assert is_tokenwise_product_question(prompt) is True


@pytest.mark.parametrize(
    "prompt",
    [
        "Explain this Python function.",
        "Fix this React bug.",
        "Translate this text to French.",
        "Write a unit test for add().",
        "Summarize this document.",
        "How do I choose between a local and external database?",
    ],
)
def test_unrelated_prompts_not_detected(prompt):
    assert is_tokenwise_product_question(prompt) is False


def test_unrelated_prompts_remain_ungrounded():
    system, grounded = resolve_system_prompt("Explain this Python function.")
    assert grounded is False
    assert system == ""


def test_product_prompts_receive_grounding_context():
    system, grounded = resolve_system_prompt(
        "Explain how TokenWise chooses between a local model and an external model."
    )
    assert grounded is True
    assert "rule-based" in system.lower()
    assert "langgraph" in system.lower()


def test_grounding_identifies_rule_based_routing():
    text = build_grounded_system_prompt().lower()
    assert "rule-based" in text
    assert "langgraph" in text
    assert "not learned" in text
    assert "input guardrails" in text
    assert "semantic cache" in text
    assert "policy_mode" in text
    assert "fall back" in text or "fallback" in text
    assert "general implemented decision flow" in text


def test_unsupported_claims_explicitly_prohibited():
    text = build_grounded_system_prompt().lower()
    for phrase in (
        "system-load",
        "automatic scaling",
        "learned routing",
        "reputation ranking",
        "policy rag",
        "cursor telemetry",
        "model fit",
    ):
        assert phrase in text


def test_current_and_planned_features_distinguished():
    text = build_grounded_system_prompt()
    assert "IMPLEMENTED" in text
    assert "PARTIAL OR PLANNED" in text
    assert "UNSUPPORTED" in text


def test_compact_receipt_facts_included_when_available():
    facts = {
        "guardrail_status": "passed",
        "cache_status": "miss",
        "graph_path": "standard_optimization_path",
        "task_type": "simple_qa",
        "complexity_level": "low",
        "complexity_score": 0.2,
        "privacy_enforced": False,
        "selected_tier": "cheap",
        "huge_blob": "SHOULD_NOT_APPEAR",
        "decision_reasons": ["a", "b", "c"],
    }
    system = build_grounded_system_prompt(runtime_facts=facts)
    assert "graph_path: standard_optimization_path" in system
    assert "selected_tier: cheap" in system
    assert "SHOULD_NOT_APPEAR" not in system
    assert "decision_reasons" not in system


def test_no_complete_decision_receipt_in_prompt():
    # Simulate a fat receipt-like dict; only allow-listed keys survive.
    fat = {k: f"val-{k}" for k in ALLOWED_RUNTIME_FACT_KEYS}
    fat.update({
        "answer": "secret answer text",
        "decision_reasons": ["r1", "r2"],
        "executed_nodes": ["a", "b", "c"],
        "optimization_reason": "long text",
        "provider_attempts": ["p1", "p2", "p3", "p4", "p5", "p6"],
    })
    compact = compact_runtime_facts(fat)
    assert "answer" not in compact
    assert "decision_reasons" not in compact
    assert "executed_nodes" not in compact
    assert len(compact["provider_attempts"]) <= 5
    prompt = build_grounded_system_prompt(runtime_facts=fat)
    assert "secret answer text" not in prompt
    assert "optimization_reason" not in prompt


def test_capabilities_file_is_valid_json():
    data = json.loads(CAP_PATH.read_text(encoding="utf-8"))
    assert data["product"] == "TokenWise"
