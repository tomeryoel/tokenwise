"""MomiHelm Optimization Engine - a real, CONDITIONAL LangGraph state graph.

Day 5.1 upgrade: the graph is no longer structurally linear. After input
normalization and signal evaluation, a router (`route_request_path`) uses
LangGraph *conditional edges* to send each request down one of five distinct
execution paths:

    reject_path | cache_path | local_only_path | vision_path | standard_optimization_path

The standard path itself contains a second conditional edge
(`should_recommend_compression`) that runs the compression-recommendation node
only when the request actually warrants it (compression_path vs
skip_compression_path). All paths converge into cost estimation + final plan.

This is why LangGraph is used instead of a plain sequential pipeline: distinct,
inspectable branches with real conditional transitions. No LLM is used inside
the graph - every decision is deterministic and testable. Actual prompt
compression is NOT performed here (recommendation only).
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from policy import normalize_policy_mode

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
CACHE_THRESHOLD = 0.88
VISION_COMPLEXITY_THRESHOLD = 0.5

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
    prefer_low_cost_tier: bool
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
    # observability
    graph_path: str
    branch_reason: str
    executed_nodes: Annotated[list[str], operator.add]
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
    "write code", "code a", "build an app", "build a website", "create an app",
    "create a web app", "implement a feature",
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


def _compression_thresholds(mode: str) -> tuple[int, int]:
    """(long_threshold, very_long_threshold) in tokens, per policy mode."""
    if mode == "aggressive":
        return 150, 400
    if mode == "conservative":
        return 400, 800
    return 250, 600


# --------------------------------------------------------------------------- #
# Shared prefix nodes
# --------------------------------------------------------------------------- #
def normalize_inputs(state: OptimizerState) -> dict[str, Any]:
    prompt = state.get("prompt") or ""
    mode = normalize_policy_mode(state.get("policy_mode"))
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
        "prefer_low_cost_tier": bool(state.get("prefer_low_cost_tier", False)),
        "executed_nodes": ["normalize_inputs"],
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

    if has_image and task in {"unknown", "simple_qa"}:
        task, reason = "image_analysis", "image attached with no stronger text signal"

    return {"task_type": task, "executed_nodes": ["classify_task"],
            "decision_reasons": [f"task_type={task} ({reason})"]}


def estimate_complexity(state: OptimizerState) -> dict[str, Any]:
    """Multi-signal complexity score in [0,1] (not just prompt length)."""
    tokens = state.get("estimated_tokens", 0)
    task = state.get("task_type", "unknown")
    text = (state.get("prompt") or "").lower()

    factors: list[str] = []
    score = 0.0

    length_signal = clamp01(tokens / 400.0) * 0.30
    score += length_signal
    factors.append(f"length {tokens}t->{round(length_signal, 2)}")

    task_weight = {
        "simple_qa": 0.05, "support_request": 0.10, "translation": 0.15,
        "summarization": 0.20, "image_analysis": 0.35, "code": 0.45,
        "document_analysis": 0.50, "complex_reasoning": 0.60, "unknown": 0.20,
    }.get(task, 0.20)
    score += task_weight
    factors.append(f"task {task}->{task_weight}")

    reasoning_hits = sum(1 for k in REASONING_KEYWORDS if k in text)
    if reasoning_hits:
        bump = min(0.20, reasoning_hits * 0.07)
        score += bump
        factors.append(f"reasoning x{reasoning_hits}->+{round(bump, 2)}")

    if task in {"code", "document_analysis"}:
        score += 0.10
        factors.append("code/doc->+0.1")

    img_c = float(state.get("image_complexity") or 0.0)
    if state.get("has_image") and img_c > 0:
        bump = clamp01(img_c) * 0.15
        score += bump
        factors.append(f"image->+{round(bump, 2)}")

    quality = (state.get("quality_requirement") or "").lower()
    if quality == "high":
        score += 0.10
        factors.append("quality=high->+0.1")

    score = round(clamp01(score), 3)
    level = "low" if score <= 0.30 else "medium" if score <= 0.65 else "high"

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
        "executed_nodes": ["estimate_complexity"],
        "decision_reasons": [
            f"complexity={score} ({level}) [{'; '.join(factors)}]",
            f"quality_requirement={quality}",
        ],
    }


def evaluate_sensitivity(state: OptimizerState) -> dict[str, Any]:
    sensitive = bool(state.get("contains_sensitive_data", False))
    require_local = bool(state.get("require_local_model", False)) or sensitive
    allow_external = bool(state.get("allow_external_model", True)) and not require_local
    reason = ("sensitive/require_local -> external models prohibited"
              if require_local else "no sensitive data; external models permitted")
    return {
        "require_local_model": require_local,
        "allow_external_model": allow_external,
        "contains_sensitive_data": sensitive,
        "executed_nodes": ["evaluate_sensitivity"],
        "decision_reasons": [reason],
    }


def evaluate_cache_signal(state: OptimizerState) -> dict[str, Any]:
    status = state.get("cache_status", "miss")
    conf = float(state.get("cache_confidence") or 0.0)
    reasons = []
    if status == "hit" and conf >= CACHE_THRESHOLD:
        reasons.append(f"cache hit signal (conf={conf}) meets threshold")
    return {"executed_nodes": ["evaluate_cache_signal"], "decision_reasons": reasons}


def route_request_path(state: OptimizerState) -> dict[str, Any]:
    """Decide which execution path this request takes and record it. The actual
    LangGraph conditional edge (see `_pick_path`) reads `graph_path` from here."""
    if state.get("guardrail_status") == "blocked":
        path = "reject_path"
        reason = f"guardrail blocked ({state.get('guardrail_reason', 'blocked')})"
    elif (state.get("cache_status") == "hit"
          and float(state.get("cache_confidence") or 0.0) >= CACHE_THRESHOLD):
        path = "cache_path"
        reason = f"cache hit (conf={state.get('cache_confidence')}) >= {CACHE_THRESHOLD}"
    elif state.get("require_local_model") or not state.get("allow_external_model", True):
        path = "local_only_path"
        reason = "privacy: sensitive/require_local -> local only"
    elif (state.get("has_image")
          and float(state.get("image_complexity") or 0.0) >= VISION_COMPLEXITY_THRESHOLD):
        path = "vision_path"
        reason = f"image complexity {state.get('image_complexity')} >= {VISION_COMPLEXITY_THRESHOLD}"
    else:
        path = "standard_optimization_path"
        reason = "normal non-sensitive cache-miss request"
    return {
        "graph_path": path,
        "branch_reason": reason,
        "executed_nodes": ["route_request_path"],
        "decision_reasons": [f"graph_path={path} ({reason})"],
    }


# --------------------------------------------------------------------------- #
# Terminal path nodes (reject / cache / local-only / vision)
# --------------------------------------------------------------------------- #
def reject_path(state: OptimizerState) -> dict[str, Any]:
    return {
        "selected_tier": "reject",
        "compression_recommended": False,
        "compression_target_ratio": RATIO_NONE,
        "compression_reason": "n/a: request rejected",
        "compression_risk": "low",
        "fallback_tier": "none",
        "fallback_reason": "request rejected; no model execution",
        "escalation_conditions": [],
        "executed_nodes": ["reject_path"],
        "decision_reasons": [
            f"reject_path: guardrail blocked ({state.get('guardrail_reason', 'blocked')})"
        ],
    }


def cache_path(state: OptimizerState) -> dict[str, Any]:
    return {
        "selected_tier": "cache",
        "compression_recommended": False,
        "compression_target_ratio": RATIO_NONE,
        "compression_reason": "n/a: served from semantic cache",
        "compression_risk": "low",
        "fallback_tier": "cheap",
        "fallback_reason": "defensive: cache invalidated -> regenerate on cheap tier",
        "escalation_conditions": ["cache entry stale/invalid -> regenerate"],
        "executed_nodes": ["cache_path"],
        "decision_reasons": ["cache_path: reuse semantic cache answer, no model call"],
    }


def local_only_path(state: OptimizerState) -> dict[str, Any]:
    return {
        "selected_tier": "local",
        "compression_recommended": False,
        "compression_target_ratio": RATIO_NONE,
        "compression_reason": "sensitive: preserve facts; no external compression",
        "compression_risk": "low",
        "fallback_tier": "none",
        "fallback_reason": "sensitive local-only request: no external fallback",
        "escalation_conditions": ["local-only: no escalation to external providers"],
        "executed_nodes": ["local_only_path"],
        "decision_reasons": ["local_only_path: privacy requires local model, external prohibited"],
    }


def vision_path(state: OptimizerState) -> dict[str, Any]:
    return {
        "selected_tier": "vision",
        "compression_recommended": False,
        "compression_target_ratio": RATIO_NONE,
        "compression_reason": "n/a: vision request",
        "compression_risk": "low",
        "fallback_tier": "premium",
        "fallback_reason": "vision model unavailable -> premium multimodal fallback",
        "escalation_conditions": ["vision provider down -> premium multimodal"],
        "executed_nodes": ["vision_path"],
        "decision_reasons": [
            f"vision_path: image complexity {state.get('image_complexity')} requires vision model"
        ],
    }


# --------------------------------------------------------------------------- #
# Standard path nodes
# --------------------------------------------------------------------------- #
def apply_policy_mode(state: OptimizerState) -> dict[str, Any]:
    mode = state.get("policy_mode", "balanced")
    notes = {
        "conservative": "conservative: prioritize quality, minimal compression",
        "balanced": "balanced: cheapest tier that meets quality",
        "aggressive": "aggressive: prioritize savings, prefer local/cheap",
    }.get(mode, "balanced")
    return {"executed_nodes": ["apply_policy_mode"], "decision_reasons": [notes]}


def decide_compression(state: OptimizerState) -> dict[str, Any]:
    """Only runs on the compression_path branch (long-enough prompts)."""
    tokens = state.get("estimated_tokens", 0)
    mode = state.get("policy_mode", "balanced")
    sensitive = state.get("contains_sensitive_data", False)
    long_t, very_long_t = _compression_thresholds(mode)

    if tokens >= very_long_t:
        ratio = RATIO_AGGRESSIVE if mode == "aggressive" else RATIO_MEDIUM
        reason = f"very long prompt ({tokens}t) under {mode} policy"
    else:
        ratio = RATIO_MEDIUM if mode == "aggressive" else RATIO_LIGHT
        reason = f"long prompt ({tokens}t) under {mode} policy"

    risk = "low" if ratio >= RATIO_LIGHT else "medium" if ratio >= RATIO_MEDIUM else "high"
    if risk == "high" and mode != "aggressive":
        ratio, risk = RATIO_MEDIUM, "medium"
        reason += " (capped: high-risk compression avoided)"
    if sensitive and ratio < RATIO_LIGHT:
        ratio, risk = RATIO_LIGHT, "medium"
        reason += " (sensitive: preserve facts/system instructions)"

    return {
        "compression_recommended": True,
        "compression_target_ratio": ratio,
        "compression_reason": reason,
        "compression_risk": risk,
        "executed_nodes": ["decide_compression"],
        "decision_reasons": [f"compression=True ratio={ratio} risk={risk}"],
    }


def skip_compression(state: OptimizerState) -> dict[str, Any]:
    tokens = state.get("estimated_tokens", 0)
    mode = state.get("policy_mode", "balanced")
    return {
        "compression_recommended": False,
        "compression_target_ratio": RATIO_NONE,
        "compression_reason": f"prompt length ({tokens}t) below {mode} compression threshold",
        "compression_risk": "low",
        "executed_nodes": ["skip_compression"],
        "decision_reasons": [f"compression skipped (short prompt for {mode})"],
    }


def select_model_tier(state: OptimizerState) -> dict[str, Any]:
    """Standard-path tier selection by complexity x policy x quality."""
    mode = state.get("policy_mode", "balanced")
    level = state.get("complexity_level", "medium")
    quality = state.get("quality_requirement", "medium")
    reasons: list[str] = []

    if level == "low":
        tier = "local" if mode == "aggressive" else "cheap"
        reasons.append(f"low complexity under {mode} -> {tier}")
    elif level == "medium":
        if mode == "aggressive":
            tier = "cheap"
        elif mode == "conservative":
            tier = "balanced"
        else:
            tier = "cheap" if quality == "low" else "balanced"
        reasons.append(f"medium complexity under {mode} (quality={quality}) -> {tier}")
    else:  # high
        if mode == "aggressive":
            tier = "premium" if quality == "high" else "balanced"
        elif mode == "conservative":
            tier = "premium"
        else:
            tier = "premium" if quality == "high" else "balanced"
        reasons.append(f"high complexity under {mode} (quality={quality}) -> {tier}")

    if (
        state.get("prefer_low_cost_tier")
        and level in {"low", "medium"}
        and quality != "high"
    ):
        order = ["local", "cheap", "balanced", "premium"]
        if tier in order and order.index(tier) > order.index("cheap"):
            tier = "cheap"
            reasons.append("cost guardrail: low-context request capped at cheap tier")
        else:
            reasons.append("cost guardrail: existing local/cheap tier already satisfies cap")

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

    return {"selected_tier": tier, "executed_nodes": ["select_model_tier"],
            "decision_reasons": reasons}


def build_fallback_plan(state: OptimizerState) -> dict[str, Any]:
    tier = state.get("selected_tier", "cheap")
    allow_external = state.get("allow_external_model", True)
    escalation = ["cheap/balanced fail quality check -> escalate one tier"]

    if tier == "cheap":
        fb, reason = "balanced", "cheap fails quality validation -> balanced"
    elif tier == "balanced":
        fb = "premium" if allow_external else "local"
        reason = ("balanced fails quality validation -> premium"
                  if allow_external else "external not permitted -> local")
    elif tier == "premium":
        fb, reason = "balanced", "premium provider unavailable -> balanced provider fallback"
    elif tier == "local":
        fb = "cheap" if allow_external else "none"
        reason = ("local unavailable and external permitted -> cheap"
                  if allow_external else "local-only: no external fallback")
    else:
        fb, reason = "balanced", "generic quality fallback"

    return {
        "fallback_tier": fb,
        "fallback_reason": reason,
        "escalation_conditions": escalation,
        "executed_nodes": ["build_fallback_plan"],
        "decision_reasons": [f"fallback={fb} ({reason})"],
    }


# --------------------------------------------------------------------------- #
# Convergence nodes (shared by every path)
# --------------------------------------------------------------------------- #
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
        "executed_nodes": ["calculate_estimated_savings"],
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
        "local_only": bool(state.get("require_local_model", False)) or tier == "local",
        "allow_external": bool(state.get("allow_external_model", True)) and tier != "local",
        "fallback_tier": state.get("fallback_tier", "balanced"),
    }
    return {"optimization_plan": plan, "executed_nodes": ["build_optimization_plan"],
            "decision_reasons": ["optimization plan assembled"]}


# --------------------------------------------------------------------------- #
# Conditional edge routers (return the mapping KEY, not state)
# --------------------------------------------------------------------------- #
def _pick_path(state: OptimizerState) -> str:
    return state.get("graph_path", "standard_optimization_path")


def should_recommend_compression(state: OptimizerState) -> str:
    tokens = state.get("estimated_tokens", 0)
    mode = state.get("policy_mode", "balanced")
    long_t, _ = _compression_thresholds(mode)
    return "compression_path" if tokens >= long_t else "skip_compression_path"


# --------------------------------------------------------------------------- #
# Graph assembly
# --------------------------------------------------------------------------- #
def build_graph():
    g = StateGraph(OptimizerState)

    # shared prefix
    g.add_node("normalize_inputs", normalize_inputs)
    g.add_node("classify_task", classify_task)
    g.add_node("estimate_complexity", estimate_complexity)
    g.add_node("evaluate_sensitivity", evaluate_sensitivity)
    g.add_node("evaluate_cache_signal", evaluate_cache_signal)
    g.add_node("route_request_path", route_request_path)
    # terminal paths
    g.add_node("reject_path", reject_path)
    g.add_node("cache_path", cache_path)
    g.add_node("local_only_path", local_only_path)
    g.add_node("vision_path", vision_path)
    # standard path
    g.add_node("apply_policy_mode", apply_policy_mode)
    g.add_node("decide_compression", decide_compression)
    g.add_node("skip_compression", skip_compression)
    g.add_node("select_model_tier", select_model_tier)
    g.add_node("build_fallback_plan", build_fallback_plan)
    # convergence
    g.add_node("calculate_estimated_savings", calculate_estimated_savings)
    g.add_node("build_optimization_plan", build_optimization_plan)

    g.add_edge(START, "normalize_inputs")
    g.add_edge("normalize_inputs", "classify_task")
    g.add_edge("classify_task", "estimate_complexity")
    g.add_edge("estimate_complexity", "evaluate_sensitivity")
    g.add_edge("evaluate_sensitivity", "evaluate_cache_signal")
    g.add_edge("evaluate_cache_signal", "route_request_path")

    # CONDITIONAL EDGE #1: request path
    g.add_conditional_edges(
        "route_request_path",
        _pick_path,
        {
            "reject_path": "reject_path",
            "cache_path": "cache_path",
            "local_only_path": "local_only_path",
            "vision_path": "vision_path",
            "standard_optimization_path": "apply_policy_mode",
        },
    )

    # terminal paths converge straight to cost estimation
    g.add_edge("reject_path", "calculate_estimated_savings")
    g.add_edge("cache_path", "calculate_estimated_savings")
    g.add_edge("local_only_path", "calculate_estimated_savings")
    g.add_edge("vision_path", "calculate_estimated_savings")

    # CONDITIONAL EDGE #2: compression recommendation (standard path only)
    g.add_conditional_edges(
        "apply_policy_mode",
        should_recommend_compression,
        {
            "compression_path": "decide_compression",
            "skip_compression_path": "skip_compression",
        },
    )
    g.add_edge("decide_compression", "select_model_tier")
    g.add_edge("skip_compression", "select_model_tier")
    g.add_edge("select_model_tier", "build_fallback_plan")
    g.add_edge("build_fallback_plan", "calculate_estimated_savings")

    g.add_edge("calculate_estimated_savings", "build_optimization_plan")
    g.add_edge("build_optimization_plan", END)
    return g.compile()


# Compile once at import; the graph is stateless per-invocation.
_GRAPH = build_graph()


def run_optimizer(request: dict[str, Any]) -> dict[str, Any]:
    """Invoke the conditional LangGraph optimizer; return the final state dict."""
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
        "prefer_low_cost_tier": bool(request.get("prefer_low_cost_tier", False)),
        "guardrail_status": request.get("guardrail_status") or "passed",
        "guardrail_reason": request.get("guardrail_reason") or "",
        "cache_status": request.get("cache_status") or "miss",
        "cache_confidence": float(request.get("cache_confidence") or 0.0),
        "has_image": bool(request.get("has_image", False)),
        "image_class": request.get("image_class") or "",
        "image_complexity": float(request.get("image_complexity") or 0.0),
        "max_cost": request.get("max_cost"),
        "executed_nodes": [],
        "decision_reasons": [],
    }
    return _GRAPH.invoke(initial)


def mermaid() -> str:
    """Return the compiled graph as Mermaid text (uses LangGraph's built-in
    exporter; no extra visualization libraries).

    Usage: python -c "from graph import mermaid; print(mermaid())"
    """
    return _GRAPH.get_graph().draw_mermaid()
