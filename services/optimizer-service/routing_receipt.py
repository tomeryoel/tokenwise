"""Canonical RoutingDecisionReceipt v1 vocabulary (transparency only).

This module does not make routing decisions. It describes decisions that other
modules already made:

* the LangGraph tier decision (graph.py)
* provider/model resolution (providers/registry.py, providers/executor.py)
* the heuristic Cursor path/model advisor (cursor/router.py)
* terminal n8n branches (cache hit, guardrail block, vision, provider error)

Every stage is reported separately (recommended -> selected -> executed) and
unknown values stay null so the UI can render "Not recorded" instead of an
invented provider or model. v1 never emits an evidence_based basis and never
claims calibrated confidence.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ROUTING_RECEIPT_VERSION = "routing_receipt_v1"

RoutingPath = Literal[
    "local_ollama",
    "cursor_sdk",
    "external_model",
    "local_service",
    "semantic_cache",
    "no_execution",
]
RoutingTier = Literal[
    "local",
    "cheap",
    "balanced",
    "premium",
    "vision",
    "cache",
    "none",
]
# evidence_based is intentionally absent in v1.
RecommendationBasis = Literal["heuristic", "configured"]
AlternativeKind = Literal[
    "cheaper",
    "stronger",
    "safer",
    "unavailable",
    "blocked_by_policy",
]
RoutingReasonCode = Literal[
    "simple_task",
    "explanation_only",
    "summary_only",
    "lightweight_planning",
    "no_repo_edit_required",
    "local_model_available",
    "local_model_unavailable",
    "cost_saving_available",
    "repo_edit_required",
    "diff_capture_required",
    "validation_required",
    "multi_file_reasoning",
    "higher_risk_change",
    "local_model_insufficient",
    "policy_requires_stronger_model",
    "policy_requires_local_model",
    "policy_blocks_external_model",
    "external_model_configured",
    "external_model_unavailable",
    "user_selected_paid_path",
    "semantic_cache_hit",
    "guardrail_blocked",
    "provider_fallback",
    "selected_differs_from_recommended",
    "executed_differs_from_selected",
    "no_applicable_alternative",
]
RoutingAssumptionCode = Literal[
    "no_historical_performance_data",
    "static_model_catalog",
    "heuristic_task_classification",
    "ollama_health_passed",
    "ollama_health_unknown",
    "cursor_bridge_health_passed",
    "cursor_bridge_health_unknown",
    "external_provider_configured",
    "external_provider_not_configured",
    "task_requires_repository_edits",
    "validation_command_provided",
    "no_repository_edit_detected",
    "policy_allows_local_model",
    "policy_allows_external_model",
]
CostEfficiencyCode = Literal[
    "local_capability_sufficient",
    "paid_execution_justified",
    "stronger_model_justified",
    "cache_reuse_avoided_model_call",
    "no_execution_no_model_cost",
    "cost_comparison_unavailable",
]

# Frozen vocabularies. Contract tests compare these against the n8n workflow and
# the frontend so the three layers cannot drift apart silently.
ROUTING_PATHS: tuple[str, ...] = (
    "local_ollama",
    "cursor_sdk",
    "external_model",
    "local_service",
    "semantic_cache",
    "no_execution",
)
ROUTING_TIERS: tuple[str, ...] = (
    "local",
    "cheap",
    "balanced",
    "premium",
    "vision",
    "cache",
    "none",
)
RECOMMENDATION_BASES: tuple[str, ...] = ("heuristic", "configured")
ALTERNATIVE_KINDS: tuple[str, ...] = (
    "cheaper",
    "stronger",
    "safer",
    "unavailable",
    "blocked_by_policy",
)
REASON_CODES: tuple[str, ...] = tuple(RoutingReasonCode.__args__)  # type: ignore[attr-defined]
ASSUMPTION_CODES: tuple[str, ...] = tuple(RoutingAssumptionCode.__args__)  # type: ignore[attr-defined]
COST_EFFICIENCY_CODES: tuple[str, ...] = tuple(CostEfficiencyCode.__args__)  # type: ignore[attr-defined]

TIER_ORDER: tuple[str, ...] = ("local", "cheap", "balanced", "premium")


class RoutingTarget(BaseModel):
    """One routing stage. Unknown parts stay null; nothing is invented."""

    path: RoutingPath | None = None
    tier: RoutingTier | None = None
    provider: str | None = None
    model: str | None = None


class RoutingConfidence(BaseModel):
    value: float | None = Field(default=None, ge=0.0, le=1.0)
    calibration: Literal["not_calibrated"] = "not_calibrated"


class RoutingAlternative(BaseModel):
    kind: AlternativeKind
    target: RoutingTarget | None = None
    reason_codes: list[RoutingReasonCode] = Field(default_factory=list)


class RoutingCostEfficiency(BaseModel):
    code: CostEfficiencyCode = "cost_comparison_unavailable"
    estimated_baseline_cost_usd: float | None = None
    estimated_selected_cost_usd: float | None = None
    actual_executed_cost_usd: float | None = None
    estimated_savings_usd: float | None = None


class RoutingFingerprints(BaseModel):
    prompt: str | None = None
    result: str | None = None
    diff: str | None = None


class RoutingDecisionReceipt(BaseModel):
    version: Literal["routing_receipt_v1"] = ROUTING_RECEIPT_VERSION
    recommended: RoutingTarget = Field(default_factory=RoutingTarget)
    selected: RoutingTarget = Field(default_factory=RoutingTarget)
    executed: RoutingTarget = Field(default_factory=RoutingTarget)
    basis: RecommendationBasis = "heuristic"
    reason_codes: list[RoutingReasonCode] = Field(default_factory=list)
    assumptions: list[RoutingAssumptionCode] = Field(default_factory=list)
    confidence: RoutingConfidence = Field(default_factory=RoutingConfidence)
    alternatives: list[RoutingAlternative] = Field(default_factory=list)
    cost_efficiency: RoutingCostEfficiency = Field(default_factory=RoutingCostEfficiency)
    fingerprints: RoutingFingerprints = Field(default_factory=RoutingFingerprints)


def blank_target() -> RoutingTarget:
    return RoutingTarget()


def clean(value: object) -> str | None:
    """Normalize provider/model strings; placeholders become null."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text == "-":
        return None
    return text


def normalize_tier(value: object) -> str | None:
    tier = clean(value)
    if tier is None:
        return None
    tier = tier.lower()
    if tier in ROUTING_TIERS:
        return tier
    if tier in {"reject", "blocked"}:
        return "none"
    if tier == "fallback":
        return "balanced"
    return None


def path_for_provider(provider: object) -> str | None:
    """Map a provider name to a routing path. Unknown providers stay null."""
    name = clean(provider)
    if name is None:
        return None
    lowered = name.lower()
    if lowered.startswith("not called"):
        return None
    if lowered == "ollama":
        return "local_ollama"
    if lowered == "openai":
        return "external_model"
    if lowered in {"cursor-sdk", "cursor_sdk", "cursor"}:
        return "cursor_sdk"
    if lowered in {"image-analyser-service", "image_analyser_service"}:
        return "local_service"
    return None


def target(
    *,
    path: str | None = None,
    tier: object = None,
    provider: object = None,
    model: object = None,
) -> RoutingTarget:
    """Build a target, deriving the path from the provider when possible."""
    resolved_provider = clean(provider)
    resolved_path = path or path_for_provider(resolved_provider)
    return RoutingTarget(
        path=resolved_path if resolved_path in ROUTING_PATHS else None,
        tier=normalize_tier(tier),
        provider=resolved_provider,
        model=clean(model),
    )


def cache_target() -> RoutingTarget:
    return RoutingTarget(path="semantic_cache", tier="cache")


def no_execution_target() -> RoutingTarget:
    return RoutingTarget(path="no_execution", tier="none")


def tier_rank(tier: str | None) -> int | None:
    if tier in TIER_ORDER:
        return TIER_ORDER.index(tier)
    return None


def is_paid_path(path: str | None) -> bool:
    return path in {"cursor_sdk", "external_model"}


def mismatch_reason_codes(
    recommended: RoutingTarget,
    selected: RoutingTarget,
    executed: RoutingTarget,
) -> list[str]:
    """Report stage mismatches. Missing stages are not treated as mismatches."""
    codes: list[str] = []

    if _stages_differ(recommended, selected):
        codes.append("selected_differs_from_recommended")
        if is_paid_path(selected.path) and recommended.path == "local_ollama":
            codes.append("user_selected_paid_path")
    if _stages_differ(selected, executed):
        codes.append("executed_differs_from_selected")
    return codes


def _stages_differ(first: RoutingTarget, second: RoutingTarget) -> bool:
    if first.path is None or second.path is None:
        # An unrecorded stage is not evidence of a mismatch.
        comparable = [
            (first.path, second.path),
            (first.provider, second.provider),
            (first.model, second.model),
        ]
        return any(
            left is not None and right is not None and left != right
            for left, right in comparable
        )
    if first.path != second.path:
        return True
    for left, right in ((first.provider, second.provider), (first.model, second.model)):
        if left is not None and right is not None and left != right:
            return True
    return False


def dedupe(codes: list[str], allowed: tuple[str, ...]) -> list[str]:
    """Keep known codes only, in first-seen order."""
    seen: set[str] = set()
    result: list[str] = []
    for code in codes:
        if code in allowed and code not in seen:
            seen.add(code)
            result.append(code)
    return result


def cost_efficiency_code_for(path: str | None) -> str:
    if path == "semantic_cache":
        return "cache_reuse_avoided_model_call"
    if path == "no_execution":
        return "no_execution_no_model_cost"
    if path in {"local_ollama", "local_service"}:
        return "local_capability_sufficient"
    if path in {"external_model", "cursor_sdk"}:
        return "paid_execution_justified"
    return "cost_comparison_unavailable"


class ProviderAvailability(BaseModel):
    """Configuration facts used to describe (not change) provider resolution.

    Everything here comes from tier->provider/model configuration lookups. No
    health probe is performed, so health assumptions stay "unknown".
    """

    resolved_provider: str | None = None
    resolved_model: str | None = None
    resolved_tier: str | None = None
    external_configured: bool = False
    local_model_for_local_tier: str | None = None
    stronger_tier: str | None = None
    stronger_external_model: str | None = None


def build_graph_recommendation(
    *,
    graph_path: str,
    selected_tier: str,
    task_type: str,
    complexity_level: str,
    policy_mode: str,
    privacy_enforced: bool,
    allow_external_model: bool,
    availability: ProviderAvailability,
    estimated_baseline_cost: float | None = None,
    estimated_optimized_cost: float | None = None,
    estimated_savings: float | None = None,
) -> RoutingDecisionReceipt:
    """Describe the optimizer's tier decision as a v1 recommendation.

    Only the `recommended` stage is filled here. `selected` and `executed` are
    added later by provider execution and the n8n convergence step.
    """
    tier = normalize_tier(selected_tier)
    reason_codes: list[str] = []
    assumptions: list[str] = ["no_historical_performance_data", "static_model_catalog"]

    if graph_path == "reject_path":
        recommended = no_execution_target()
        reason_codes.append("guardrail_blocked")
        basis: str = "configured"
    elif graph_path == "cache_path":
        recommended = cache_target()
        reason_codes.append("semantic_cache_hit")
        basis = "configured"
    elif tier == "vision":
        recommended = RoutingTarget(path="local_service", tier="vision")
        reason_codes.append("no_repo_edit_required")
        basis = "configured"
    else:
        # The tier is MomiHelm's own recommendation; provider/model come from
        # current configuration. A configured local model can sit below the
        # recommended tier, which stays visible as a per-stage tier difference.
        recommended = target(
            tier=tier,
            provider=availability.resolved_provider,
            model=availability.resolved_model,
        )
        if recommended.path is None:
            recommended.path = "local_ollama" if privacy_enforced else None
        reason_codes.append("no_repo_edit_required")
        assumptions.append("heuristic_task_classification")
        assumptions.append("no_repository_edit_detected")

        if complexity_level == "low":
            reason_codes.append("simple_task")
        if task_type == "simple_qa":
            reason_codes.append("explanation_only")
        elif task_type == "summarization":
            reason_codes.append("summary_only")

        if recommended.path == "local_ollama":
            reason_codes.append("local_model_available")
            if tier in {"cheap", "balanced", "premium"} and not privacy_enforced:
                reason_codes.append("external_model_unavailable")
            if estimated_savings:
                reason_codes.append("cost_saving_available")
        elif recommended.path == "external_model":
            reason_codes.append("external_model_configured")

        if privacy_enforced:
            reason_codes.append("policy_requires_local_model")
        if not allow_external_model:
            reason_codes.append("policy_blocks_external_model")
        if policy_mode == "conservative" and tier == "premium":
            reason_codes.append("policy_requires_stronger_model")

        # Policy/configuration decided the outcome outright, or the complexity
        # heuristics did. Provider availability alone does not make it
        # "configured": the tier still came from heuristic classification.
        basis = "configured" if (privacy_enforced or not allow_external_model) else "heuristic"

    if recommended.path == "local_ollama":
        assumptions.append("ollama_health_unknown")
        assumptions.append("policy_allows_local_model")
    assumptions.append(
        "external_provider_configured"
        if availability.external_configured
        else "external_provider_not_configured"
    )
    if allow_external_model and not privacy_enforced:
        assumptions.append("policy_allows_external_model")

    alternatives = _graph_alternatives(
        recommended=recommended,
        privacy_enforced=privacy_enforced,
        allow_external_model=allow_external_model,
        availability=availability,
    )

    return RoutingDecisionReceipt(
        recommended=recommended,
        basis=basis,  # type: ignore[arg-type]
        reason_codes=dedupe(reason_codes, REASON_CODES),  # type: ignore[arg-type]
        assumptions=dedupe(assumptions, ASSUMPTION_CODES),  # type: ignore[arg-type]
        confidence=RoutingConfidence(value=0.9 if basis == "configured" else 0.55),
        alternatives=alternatives,
        cost_efficiency=RoutingCostEfficiency(
            code=cost_efficiency_code_for(recommended.path),  # type: ignore[arg-type]
            estimated_baseline_cost_usd=estimated_baseline_cost,
            estimated_selected_cost_usd=estimated_optimized_cost,
            estimated_savings_usd=estimated_savings,
        ),
    )


def _graph_alternatives(
    *,
    recommended: RoutingTarget,
    privacy_enforced: bool,
    allow_external_model: bool,
    availability: ProviderAvailability,
) -> list[RoutingAlternative]:
    """Only real configured candidates become alternatives."""
    alternatives: list[RoutingAlternative] = []
    if recommended.path in {"semantic_cache", "no_execution", "local_service"}:
        return [
            RoutingAlternative(
                kind="unavailable",
                reason_codes=["no_applicable_alternative"],
            )
        ]

    local_model = clean(availability.local_model_for_local_tier)
    # A local recommendation already costs nothing, so there is no cheaper
    # alternative to offer. Naming a different local tier that resolves to the
    # same model would be an invented saving.
    if (
        local_model is not None
        and recommended.path != "local_ollama"
        and local_model != recommended.model
    ):
        alternatives.append(
            RoutingAlternative(
                kind="cheaper",
                target=RoutingTarget(
                    path="local_ollama",
                    tier="local",
                    provider="ollama",
                    model=local_model,
                ),
                reason_codes=["cost_saving_available", "local_model_available"],
            )
        )

    stronger_tier = normalize_tier(availability.stronger_tier)
    stronger_model = clean(availability.stronger_external_model)
    if stronger_tier is not None:
        if not allow_external_model or privacy_enforced:
            alternatives.append(
                RoutingAlternative(
                    kind="blocked_by_policy",
                    target=RoutingTarget(
                        path="external_model",
                        tier=stronger_tier,  # type: ignore[arg-type]
                        provider="openai",
                        model=stronger_model,
                    ),
                    reason_codes=["policy_blocks_external_model"],
                )
            )
        elif stronger_model is not None:
            alternatives.append(
                RoutingAlternative(
                    kind="stronger",
                    target=RoutingTarget(
                        path="external_model",
                        tier=stronger_tier,  # type: ignore[arg-type]
                        provider="openai",
                        model=stronger_model,
                    ),
                    reason_codes=["external_model_configured"],
                )
            )
        else:
            alternatives.append(
                RoutingAlternative(
                    kind="unavailable",
                    target=RoutingTarget(
                        path="external_model",
                        tier=stronger_tier,  # type: ignore[arg-type]
                        provider="openai",
                    ),
                    reason_codes=["external_model_unavailable"],
                )
            )

    if not alternatives:
        alternatives.append(
            RoutingAlternative(
                kind="unavailable",
                reason_codes=["no_applicable_alternative"],
            )
        )
    return alternatives


RAW_CONTENT_FIELD_HINTS: tuple[str, ...] = (
    "prompt",
    "answer",
    "diff",
    "text",
    "stdout",
    "stderr",
    "code",
    "explanation",
    "message",
)


def contains_only_metadata(payload: dict) -> bool:
    """Guard: routing metadata must never carry raw prompt/answer/diff content.

    `fingerprints` may hold hex digests, and `reason_codes`/`assumptions` hold
    enum values only. Anything else that looks like free text is rejected.
    """
    fingerprints = payload.get("fingerprints") or {}
    if not isinstance(fingerprints, dict):
        return False
    for value in fingerprints.values():
        if value is None:
            continue
        if not isinstance(value, str) or len(value) > 128 or " " in value:
            return False
    for code in list(payload.get("reason_codes") or []):
        if code not in REASON_CODES:
            return False
    for code in list(payload.get("assumptions") or []):
        if code not in ASSUMPTION_CODES:
            return False
    for key in ("recommended", "selected", "executed"):
        stage = payload.get(key) or {}
        if not isinstance(stage, dict):
            return False
        for field, value in stage.items():
            if value is None:
                continue
            if not isinstance(value, str) or len(value) > 200:
                return False
            if field in {"path", "tier"}:
                continue
            if any(hint in field for hint in RAW_CONTENT_FIELD_HINTS):
                return False
    return True
