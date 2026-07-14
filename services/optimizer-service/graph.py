"""TokenWise Optimization Engine - a real, deterministic LangGraph state graph.

This is the Day 5 replacement for the mocked optimizer. It is an explicit
multi-node graph that consumes request signals (prompt, policy_mode, guardrail
result, cache result, optional image fields) and produces a structured
Optimization Plan (selected tier, compression recommendation, fallback plan,
cost/savings estimate, and human-readable decision reasons).

No LLM is used inside the graph - all decisions are deterministic rules so the
result is testable and academically defensible. LangGraph gives us an explicit,
inspectable state machine rather than one big if/else function.
"""
from __future__ import annotations

import operator
import re
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

# --------------------------------------------------------------------------- #
# Static pricing (USD per 1k tokens). Deterministic, easy to explain.
# local is near-zero (small self-host infra estimate); cache/reject cost nothing.
# --------------------------------------------------------------------------- #
TIER_PRICE_PER_1K: dict[str, float] = {
    "local": 0.00005,
    "cheap": 0.0005,
    "balanced": 0.003,
    "premium": 0.03,
    "vision": 0.01,
    "cache": 0.0,
    "reject": 0.0,
    "fallback": 0.003,
}
PREMIUM_TIER = "premium"

# Compression target ratios (fraction of tokens kept).
RATIO_NONE = 1.0
RATIO_LIGHT = 0.85
RATIO_MEDIUM = 0.65
RATIO_AGGRESSIVE = 0.50


# --------------------------------------------------------------------------- #
# Graph state
# --------------------------------------------------------------------------- #
class OptimizerState(TypedDict, total=False):
    # inputs
    request_id: str
    prompt: str
    policy_mode: str
    task_type: str
    estimated_tokens: int
    complexity_score: float
    complexity_level: str
    quality_requirement: str
    latency_requirement: str
    contains_sensitive_data: bool
    require_local_model: bool
    allow_external_model: bool
    guardrail_status: str
    guardrail_reason: str
    cache_status: str
    cache_confidence: float
    has_image: bool
    image_class: str
    image_complexity: float
    max_cost: Optional[float]
    # decisions
    selected_tier: str
    compression_recommended: bool
    compression_target_ratio: float
    compression_reason: str
    compression_risk: str
    fallback_tier: str
    fallback_reason: str
    escalation_conditions: list[str]
    estimated_baseline_cost: float
    estimated_optimized_cost: float
    estimated_savings: float
    # decision_reasons accumulates across nodes via the operator.add reducer
    decision_reasons: Annotated[list[str], operator.add]
    optimization_plan: dict[str, Any]


# --------------------------------------------------------------------------- #
# Keyword rule tables (task classification + complexity signals)
# --------------------------------------------------------------------------- #
SUPPORT_KEYWORDS = [
    "reset my password", "reset password", "password", "login", "log in",
    "account", "cannot access", "can't access", "help desk", "helpdesk",
    "ticket", "support", "unlock", "billing issue",
]
SUMMARIZE_KEYWORDS = ["summarize", "summarise", "summary", "tl;dr", "tldr", "condense"]
TRANSLATE_KEYWORDS = ["translate", "translation", "in hebrew", "in spanish", "in french", "into hebrew"]
CODE_KEYWORDS = [
    "python", "javascript", "typescript", "java ", "c++", "function", "class ",
    "traceback", "stack trace", "compile", "bug", "refactor", "regex", "sql",
    "memory leak", "leaks memory", "code review", "review this", "unit test",
]
DOC_KEYWORDS = [
    "document", "contract", "invoice", "report", "spreadsheet", "pdf",
    "extract fields", "analyse this document", "analyze this document",
]
REASONING_KEYWORDS = [
    "compare", "trade-off", "tradeoff", "tradeoffs", "design an architecture",
    "design and compare", "architecture", "evaluate", "pros and cons",
    "strategy", "reasoning", "step by step", "failure modes", "scalable",
    "end-to-end", "in depth", "in-depth",
]
QA_KEYWORDS = ["what is", "how do i", "how can", "why", "explain", "when", "where"]


def _contains_any(text: str, keywords: list[str]) -> Optional[str]:
    for k in keywords:
        if k in text:
            return k
    return None


def estimate_tokens_from_prompt(prompt: str) -> int:
    """~1.3 tokens per word, consistent with guardrails + cache services."""
    return max(1, round(len((prompt or "").split()) * 1.3))


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #
def normalize_inputs(state: OptimizerState) -> dict[str, Any]:
    prompt = state.get("prompt") or ""
    mode = (state.get("policy_mode") or "balanced").lower()
    if mode not in {"conservative", "balanced", "aggressive"}:
        mode = "balanced"
    tokens = state.get("estimated_tokens")
    if not tokens or tokens <= 0:
        tokens = estimate_tokens_from_prompt(prompt)
    return {
        "prompt": prompt,
        "policy_mode": mode,
        "estimated_tokens": tokens,
        "latency_requirement": (state.get("latency_requirement") or "normal").lower(),
        "has_image": bool(state.get("has_image", False)),
        "image_complexity": float(state.get("image_complexity") or 0.0),
        "cache_status": (state.get("cache_status") or "miss").lower(),
        "cache_confidence": float(state.get("cache_confidence") or 0.0),
        "guardrail_status": (state.get("guardrail_status") or "passed").lower(),
        "decision_reasons": [f"normalized: policy_mode={mode}, tokens={tokens}"],
    }


def classify_task(state: OptimizerState) -> dict[str, Any]:
    text = (state.get("prompt") or "").lower()
    has_image = state.get("has_image", False)

    task = "unknown"
    reason = "no strong signal; defaulted to unknown"

    hit = _contains_any(text, TRANSLATE_KEYWORDS)
    if hit:
        task, reason = "translation", f"translation keyword '{hit}'"
    elif (hit := _contains_any(text, SUMMARIZE_KEYWORDS)):
        task, reason = "summarization", f"summarization keyword '{hit}'"
    elif (hit := _contains_any(text, CODE_KEYWORDS)):
        task, reason = "code", f"code keyword '{hit}'"
    elif (hit := _contains_any(text, REASONING_KEYWORDS)):
        task, reason = "complex_reasoning", f"reasoning keyword '{hit}'"
    elif (hit := _contains_any(text, DOC_KEYWORDS)):
        task, reason = "document_analysis", f"document keyword '{hit}'"
    elif (hit := _contains_any(text, SUPPORT_KEYWORDS)):
        task, reason = "support_request", f"support keyword '{hit}'"
    elif (hit := _contains_any(text, QA_KEYWORDS)):
        task, reason = "simple_qa", f"question keyword '{hit}'"

    # Image is used only when no stronger textual signal dominates.
    if has_image and task in {"unknown", "simple_qa"}:
        task, reason = "image_analysis", "image attached with no stronger text signal"

    return {"task_type": task, "decision_reasons": [f"task_type={task} ({reason})"]}


def estimate_complexity(state: OptimizerState) -> dict[str, Any]:
    """Multi-signal complexity score in [0,1] (not just prompt length)."""
    tokens = state.get("estimated_tokens", 0)
    task = state.get("task_type", "unknown")
    text = (state.get("prompt") or "").lower()

    factors: list[str] = []
    score = 0.0

    # 1) length signal (capped)
    length_signal = clamp01(tokens / 400.0) * 0.30
    score += length_signal
    factors.append(f"length {tokens}t->{round(length_signal, 2)}")

    # 2) task-type base weight
    task_weight = {
        "simple_qa": 0.05, "support_request": 0.10, "translation": 0.15,
        "summarization": 0.20, "image_analysis": 0.35, "code": 0.45,
        "document_analysis": 0.50, "complex_reasoning": 0.60, "unknown": 0.20,
    }.get(task, 0.20)
    score += task_weight
    factors.append(f"task {task}->{task_weight}")

    # 3) reasoning keyword density
    reasoning_hits = sum(1 for k in REASONING_KEYWORDS if k in text)
    if reasoning_hits:
        bump = min(0.20, reasoning_hits * 0.07)
        score += bump
        factors.append(f"reasoning x{reasoning_hits}->+{round(bump, 2)}")

    # 4) code / document signal
    if task in {"code", "document_analysis"}:
        score += 0.10
        factors.append("code/doc->+0.1")

    # 5) image complexity signal
    img_c = float(state.get("image_complexity") or 0.0)
    if state.get("has_image") and img_c > 0:
        bump = clamp01(img_c) * 0.15
        score += bump
        factors.append(f"image->+{round(bump, 2)}")

    # 6) explicit quality requirement raises the floor
    quality = (state.get("quality_requirement") or "").lower()
    if quality == "high":
        score += 0.10
        factors.append("quality=high->+0.1")

    score = round(clamp01(score), 3)
    level = "low" if score <= 0.30 else "medium" if score <= 0.65 else "high"

    # Derive quality_requirement if not explicitly provided.
    if quality not in {"low", "medium", "high"}:
        if level == "high" or task in {"complex_reasoning", "document_analysis"}:
            quality = "high"
        elif level == "low" and task in {"simple_qa", "support_request", "translation"}:
            quality = "low"
        else:
            quality = "medium"

    return {
        "complexity_score": score,
        "complexity_level": level,
        "quality_requirement": quality,
        "decision_reasons": [
            f"complexity={score} ({level}) [{'; '.join(factors)}]",
            f"quality_requirement={quality}",
        ],
    }


def evaluate_sensitivity(state: OptimizerState) -> dict[str, Any]:
    sensitive = bool(state.get("contains_sensitive_data", False))
    require_local = bool(state.get("require_local_model", False)) or sensitive
    allow_external = bool(state.get("allow_external_model", True)) and not require_local
    reasons = []
    if require_local:
        reasons.append("sensitive/require_local -> external models prohibited")
    else:
        reasons.append("no sensitive data; external models permitted")
    return {
        "require_local_model": require_local,
        "allow_external_model": allow_external,
        "contains_sensitive_data": sensitive,
        "decision_reasons": reasons,
    }


def evaluate_cache_signal(state: OptimizerState) -> dict[str, Any]:
    """Defensive: optimizer is normally skipped on a cache hit, but if a hit
    signal arrives we honor it as a valid 'cache' tier."""
    status = state.get("cache_status", "miss")
    conf = float(state.get("cache_confidence") or 0.0)
    if status == "hit" and conf >= 0.88:
        return {"decision_reasons": [f"cache hit signal (conf={conf}) -> cache tier eligible"]}
    return {"decision_reasons": []}


def apply_policy_mode(state: OptimizerState) -> dict[str, Any]:
    mode = state.get("policy_mode", "balanced")
    notes = {
        "conservative": "conservative: prioritize quality, minimal compression",
        "balanced": "balanced: cheapest tier that meets quality",
        "aggressive": "aggressive: prioritize savings, prefer local/cheap",
    }.get(mode, "balanced")
    return {"decision_reasons": [notes]}


def decide_compression(state: OptimizerState) -> dict[str, Any]:
    tokens = state.get("estimated_tokens", 0)
    mode = state.get("policy_mode", "balanced")
    sensitive = state.get("contains_sensitive_data", False)

    # Per-mode length thresholds (in tokens).
    if mode == "aggressive":
        long_t, very_long_t = 150, 400
    elif mode == "conservative":
        long_t, very_long_t = 400, 800
    else:
        long_t, very_long_t = 250, 600

    recommended = False
    ratio = RATIO_NONE
    reason = "prompt is already short; no compression needed"

    if tokens < 60:
        recommended, ratio = False, RATIO_NONE
        reason = "prompt is already short; no compression needed"
    elif tokens >= very_long_t:
        recommended = True
        ratio = RATIO_AGGRESSIVE if mode == "aggressive" else RATIO_MEDIUM
        reason = f"very long prompt ({tokens}t) under {mode} policy"
    elif tokens >= long_t:
        recommended = True
        ratio = RATIO_MEDIUM if mode == "aggressive" else RATIO_LIGHT
        reason = f"long prompt ({tokens}t) under {mode} policy"
    else:
        recommended, ratio = False, RATIO_NONE
        reason = f"prompt length ({tokens}t) below {mode} compression threshold"

    risk = "low" if ratio >= RATIO_LIGHT else "medium" if ratio >= RATIO_MEDIUM else "high"

    # High-risk compression is skipped unless explicitly in aggressive mode.
    if risk == "high" and mode != "aggressive":
        ratio, risk = RATIO_MEDIUM, "medium"
        reason += " (capped: high-risk compression avoided)"

    # Sensitive prompts: preserve facts + system instructions -> never below light.
    if sensitive and recommended and ratio < RATIO_LIGHT:
        ratio, risk = RATIO_LIGHT, "medium"
        reason += " (sensitive: preserve facts/system instructions)"

    return {
        "compression_recommended": recommended,
        "compression_target_ratio": ratio,
        "compression_reason": reason,
        "compression_risk": risk,
        "decision_reasons": [f"compression={recommended} ratio={ratio} risk={risk}"],
    }


def select_model_tier(state: OptimizerState) -> dict[str, Any]:
    reasons: list[str] = []

    # Defensive overrides first.
    if state.get("guardrail_status") == "blocked":
        return {"selected_tier": "reject", "decision_reasons": ["guardrail blocked -> reject tier"]}

    if state.get("require_local_model"):
        return {"selected_tier": "local", "decision_reasons": ["privacy: require_local_model -> local tier"]}

    if state.get("cache_status") == "hit" and float(state.get("cache_confidence") or 0.0) >= 0.88:
        return {"selected_tier": "cache", "decision_reasons": ["cache hit -> cache tier"]}

    if state.get("has_image") and float(state.get("image_complexity") or 0.0) >= 0.5:
        return {"selected_tier": "vision", "decision_reasons": ["image requires vision -> vision tier"]}

    mode = state.get("policy_mode", "balanced")
    level = state.get("complexity_level", "medium")
    quality = state.get("quality_requirement", "medium")

    if level == "low":
        tier = "local" if mode == "aggressive" else "cheap"
        reasons.append(f"low complexity under {mode} -> {tier}")
    elif level == "medium":
        if mode == "aggressive":
            tier = "cheap"
        elif mode == "conservative":
            tier = "balanced"
        else:  # balanced: cheapest tier meeting quality
            tier = "cheap" if quality == "low" else "balanced"
        reasons.append(f"medium complexity under {mode} (quality={quality}) -> {tier}")
    else:  # high
        if mode == "aggressive":
            tier = "premium" if quality == "high" else "balanced"
        elif mode == "conservative":
            tier = "premium"
        else:  # balanced
            tier = "premium" if quality == "high" else "balanced"
        reasons.append(f"high complexity under {mode} (quality={quality}) -> {tier}")

    # Optional cost ceiling (kept simple): downgrade if optimized tier too pricey.
    max_cost = state.get("max_cost")
    if max_cost is not None:
        tokens = state.get("estimated_tokens", 0)
        order = ["local", "cheap", "balanced", "premium"]
        while tier in order and (tokens / 1000.0) * TIER_PRICE_PER_1K[tier] > max_cost:
            idx = order.index(tier)
            if idx == 0:
                break
            tier = order[idx - 1]
            reasons.append(f"cost ceiling {max_cost} -> downgraded to {tier}")

    return {"selected_tier": tier, "decision_reasons": reasons}


def build_fallback_plan(state: OptimizerState) -> dict[str, Any]:
    tier = state.get("selected_tier", "cheap")
    allow_external = state.get("allow_external_model", True)

    escalation = ["cheap/balanced fail quality check -> escalate one tier"]
    if tier == "local" and not allow_external:
        fb, reason = "none", "sensitive local-only request: no external fallback"
        escalation = ["local-only: no escalation to external providers"]
    elif tier == "local":
        fb, reason = "cheap", "local unavailable and external permitted -> cheap"
    elif tier == "cheap":
        fb, reason = "balanced", "cheap fails quality validation -> balanced"
    elif tier == "balanced":
        fb = "premium" if allow_external else "local"
        reason = "balanced fails quality validation -> premium" if allow_external else "external not permitted -> local"
    elif tier == "premium":
        fb, reason = "balanced", "premium provider unavailable -> balanced provider fallback"
    elif tier == "vision":
        fb, reason = "premium", "vision model unavailable -> premium multimodal fallback"
    elif tier == "cache":
        fb, reason = "cheap", "cache invalidated -> regenerate on cheap tier"
    else:  # reject
        fb, reason = "none", "request rejected; no model execution"

    return {
        "fallback_tier": fb,
        "fallback_reason": reason,
        "escalation_conditions": escalation,
        "decision_reasons": [f"fallback={fb} ({reason})"],
    }


def calculate_estimated_savings(state: OptimizerState) -> dict[str, Any]:
    tokens = state.get("estimated_tokens", 0)
    tier = state.get("selected_tier", "cheap")

    baseline = round(tokens / 1000.0 * TIER_PRICE_PER_1K[PREMIUM_TIER], 6)
    optimized = round(tokens / 1000.0 * TIER_PRICE_PER_1K.get(tier, TIER_PRICE_PER_1K["cheap"]), 6)
    savings = round(max(0.0, baseline - optimized), 6)

    return {
        "estimated_baseline_cost": baseline,
        "estimated_optimized_cost": optimized,
        "estimated_savings": savings,
        "decision_reasons": [
            f"baseline(premium)={baseline}, optimized({tier})={optimized}, savings={savings}"
        ],
    }


def build_optimization_plan(state: OptimizerState) -> dict[str, Any]:
    tier = state.get("selected_tier", "cheap")
    plan = {
        "route": tier,
        "compress": bool(state.get("compression_recommended", False)),
        "compression_target_ratio": state.get("compression_target_ratio", RATIO_NONE),
        "local_only": bool(state.get("require_local_model", False)),
        "allow_external": bool(state.get("allow_external_model", True)),
        "fallback_tier": state.get("fallback_tier", "balanced"),
    }
    return {"optimization_plan": plan, "decision_reasons": ["optimization plan assembled"]}


# --------------------------------------------------------------------------- #
# Graph assembly
# --------------------------------------------------------------------------- #
def build_graph():
    g = StateGraph(OptimizerState)
    g.add_node("normalize_inputs", normalize_inputs)
    g.add_node("classify_task", classify_task)
    g.add_node("estimate_complexity", estimate_complexity)
    g.add_node("evaluate_sensitivity", evaluate_sensitivity)
    g.add_node("evaluate_cache_signal", evaluate_cache_signal)
    g.add_node("apply_policy_mode", apply_policy_mode)
    g.add_node("decide_compression", decide_compression)
    g.add_node("select_model_tier", select_model_tier)
    g.add_node("build_fallback_plan", build_fallback_plan)
    g.add_node("calculate_estimated_savings", calculate_estimated_savings)
    g.add_node("build_optimization_plan", build_optimization_plan)

    g.add_edge(START, "normalize_inputs")
    g.add_edge("normalize_inputs", "classify_task")
    g.add_edge("classify_task", "estimate_complexity")
    g.add_edge("estimate_complexity", "evaluate_sensitivity")
    g.add_edge("evaluate_sensitivity", "evaluate_cache_signal")
    g.add_edge("evaluate_cache_signal", "apply_policy_mode")
    g.add_edge("apply_policy_mode", "decide_compression")
    g.add_edge("decide_compression", "select_model_tier")
    g.add_edge("select_model_tier", "build_fallback_plan")
    g.add_edge("build_fallback_plan", "calculate_estimated_savings")
    g.add_edge("calculate_estimated_savings", "build_optimization_plan")
    g.add_edge("build_optimization_plan", END)
    return g.compile()


# Compile once at import; the graph is stateless per-invocation.
_GRAPH = build_graph()


def run_optimizer(request: dict[str, Any]) -> dict[str, Any]:
    """Invoke the LangGraph optimizer and return the final state as a dict."""
    initial: OptimizerState = {
        "request_id": request.get("request_id") or "",
        "prompt": request.get("prompt") or "",
        "policy_mode": request.get("policy_mode") or "balanced",
        "estimated_tokens": int(request.get("estimated_tokens") or 0),
        "quality_requirement": request.get("quality_requirement") or "",
        "latency_requirement": request.get("latency_requirement") or "normal",
        "contains_sensitive_data": bool(request.get("contains_sensitive_data", False)),
        "require_local_model": bool(request.get("require_local_model", False)),
        "allow_external_model": bool(request.get("allow_external_model", True)),
        "guardrail_status": request.get("guardrail_status") or "passed",
        "guardrail_reason": request.get("guardrail_reason") or "",
        "cache_status": request.get("cache_status") or "miss",
        "cache_confidence": float(request.get("cache_confidence") or 0.0),
        "has_image": bool(request.get("has_image", False)),
        "image_class": request.get("image_class") or "",
        "image_complexity": float(request.get("image_complexity") or 0.0),
        "max_cost": request.get("max_cost"),
        "decision_reasons": [],
    }
    return _GRAPH.invoke(initial)
