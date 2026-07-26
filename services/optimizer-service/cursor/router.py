"""Route coding tasks to the best Cursor model."""

from __future__ import annotations

from typing import Literal, NamedTuple

from pydantic import BaseModel, Field

from cursor.models import CursorModel, get_cursor_model, load_cursor_models, normalize_cursor_model_id
from policy import PolicyMode
from routing_receipt import (
    ASSUMPTION_CODES,
    REASON_CODES,
    RoutingAlternative,
    RoutingConfidence,
    RoutingCostEfficiency,
    RoutingDecisionReceipt,
    RoutingTarget,
    dedupe,
    mismatch_reason_codes,
    tier_rank,
)


ComplexityLevel = Literal["low", "medium", "high"]
WorkflowType = Literal["direct", "plan", "agent", "debug", "review", "unknown"]


class CursorRouteRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=100_000)
    task_type: str = Field(default="unknown", max_length=80)
    complexity_level: ComplexityLevel = "medium"
    policy_mode: PolicyMode = "balanced"
    workflow: WorkflowType = "unknown"
    requested_model: str | None = Field(default=None, max_length=200)
    prefer_auto: bool = False


class CursorRouteAlternative(BaseModel):
    model_id: str
    display_name: str
    route_class: str
    momihelm_tier: str
    reason: str


class CursorRouteRecommendation(BaseModel):
    recommended_model_id: str
    recommended_display_name: str
    recommended_tier: str
    route_class: str
    resolved_from_auto: bool = False
    fallback_model_id: str | None = None
    fallback_display_name: str | None = None
    reasons: list[str] = Field(default_factory=list)
    alternatives: list[CursorRouteAlternative] = Field(default_factory=list)
    # Cost-efficient path advice. Heuristic only — not historical evidence.
    # local_ollama = use Quick Question / Coding Session via existing Ollama path.
    # cursor_sdk = use Cursor Agent Coding Run for workspace edits/validation.
    recommended_path: Literal["local_ollama", "cursor_sdk"] = "cursor_sdk"
    path_reasons: list[str] = Field(default_factory=list)
    recommendation_basis: Literal["heuristic", "configured", "evidence"] = "heuristic"
    confidence: float = Field(default=0.55, ge=0.0, le=1.0)
    # RoutingDecisionReceipt v1 recommendation stage. `selected` and `executed`
    # stay empty here; the gateway fills them from the actual SDK run.
    routing: RoutingDecisionReceipt = Field(default_factory=RoutingDecisionReceipt)


def _score_model(
    model: CursorModel,
    *,
    complexity: ComplexityLevel,
    policy_mode: PolicyMode,
    workflow: WorkflowType,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0

    complexity_target = {"low": 0.35, "medium": 0.6, "high": 0.85}[complexity]
    reasoning_gap = abs(model.relative_reasoning - complexity_target)
    reasoning_component = max(0.0, 1.0 - reasoning_gap)
    score += reasoning_component * 0.45
    reasons.append(
        f"{model.display_name} reasoning fit for {complexity} complexity "
        f"({model.relative_reasoning:.2f})"
    )

    if policy_mode == "conservative":
        cost_component = 1.0 - model.relative_cost
        score += cost_component * 0.35
        reasons.append("conservative policy favors lower-cost Cursor models")
    elif policy_mode == "aggressive":
        cost_component = 1.0 - model.relative_cost
        score += cost_component * 0.45
        reasons.append("aggressive policy prioritizes savings")
    else:
        balance_component = 1.0 - abs(model.relative_cost - 0.45)
        score += balance_component * 0.30
        reasons.append("balanced policy weighs cost and capability")

    if workflow == "agent" and model.supports_agent:
        score += 0.10
        reasons.append("agent workflow prefers agent-capable models")
    if workflow == "plan" and model.supports_plan:
        score += 0.08
        reasons.append("plan workflow prefers planning-capable models")
    if workflow == "debug" and model.route_class in {"balanced", "premium"}:
        score += 0.05
    if workflow == "review" and model.relative_reasoning >= 0.65:
        score += 0.05

    if model.route_class == "economy" and complexity == "high":
        score -= 0.20
        reasons.append("high-complexity task penalizes economy models")
    if model.route_class == "premium" and complexity == "low":
        score -= 0.15
        reasons.append("low-complexity task penalizes premium models")

    return score, reasons


def _eligible_models(workflow: WorkflowType) -> list[CursorModel]:
    models = [model for model in load_cursor_models() if model.id != "auto"]
    if workflow == "agent":
        return [model for model in models if model.supports_agent]
    if workflow == "plan":
        return [model for model in models if model.supports_plan]
    return models


class PathAdvice(NamedTuple):
    path: Literal["local_ollama", "cursor_sdk"]
    reasons: list[str]
    confidence: float
    reason_codes: list[str]
    assumptions: list[str]


def _recommend_execution_path(req: CursorRouteRequest) -> PathAdvice:
    """Heuristic path advice: local Ollama playground vs Cursor SDK coding run.

    Does not claim Ollama can edit repositories. Local path means existing
    Quick Question / Coding Session n8n→optimizer→Ollama flow.
    """
    text = req.objective.lower()
    path_reasons: list[str] = []

    edit_signals = (
        "edit ",
        "change ",
        "modify ",
        "refactor",
        "implement",
        "fix ",
        "patch ",
        "diff",
        "apply to",
        "update the file",
        "update file",
        "in hello.py",
        "in the repo",
        "repository",
        "workspace",
        "run tests",
        "pytest",
        "unit test",
        "multi-file",
        "across files",
    )
    simple_signals = (
        "explain",
        "what is",
        "what's",
        "summarize",
        "summary",
        "how does",
        "why does",
        "define ",
        "translate",
        "rewrite this sentence",
        "brainstorm",
        "outline a plan",
        "give an example",
    )

    edit_hits = sum(1 for signal in edit_signals if signal in text)
    simple_hits = sum(1 for signal in simple_signals if signal in text)
    needs_agent_workflow = req.workflow in {"agent", "debug"} and edit_hits > 0
    high_risk = req.complexity_level == "high" or req.task_type in {
        "architecture_design",
        "bug_fix",
        "feature_implementation",
        "refactor",
    }
    validation_signal = any(
        signal in text for signal in ("pytest", "run tests", "unit test", "npm test")
    )
    multi_file_signal = any(
        signal in text for signal in ("multi-file", "across files", "repository")
    )

    edit_codes = ["repo_edit_required", "diff_capture_required"]
    if validation_signal:
        edit_codes.append("validation_required")
    if multi_file_signal:
        edit_codes.append("multi_file_reasoning")
    if high_risk:
        edit_codes.append("higher_risk_change")
    edit_assumptions = ["task_requires_repository_edits"]
    simple_assumptions = ["no_repository_edit_detected"]

    if needs_agent_workflow or edit_hits >= 2 or (edit_hits >= 1 and high_risk):
        path_reasons.append(
            "repository-edit / validation signals favor Cursor SDK coding run"
        )
        if high_risk:
            path_reasons.append("task type/complexity suggests stronger coding agent")
        return PathAdvice("cursor_sdk", path_reasons, 0.7, edit_codes, edit_assumptions)

    if (
        req.complexity_level == "low"
        and simple_hits >= 1
        and edit_hits == 0
        and req.workflow in {"direct", "plan", "unknown", "review"}
    ):
        path_reasons.append(
            "simple Q&A/planning without repo-edit signals → local Ollama playground"
        )
        path_reasons.append(
            "use Quick Question or Coding Session; Cursor SDK not required"
        )
        return PathAdvice(
            "local_ollama",
            path_reasons,
            0.65,
            [
                "simple_task",
                "no_repo_edit_required",
                "lightweight_planning",
                "cost_saving_available",
            ],
            simple_assumptions,
        )

    if edit_hits == 0 and simple_hits >= 1 and req.complexity_level != "high":
        path_reasons.append(
            "explanation/summary-style objective without edit signals → prefer local Ollama"
        )
        return PathAdvice(
            "local_ollama",
            path_reasons,
            0.6,
            ["explanation_only", "no_repo_edit_required", "cost_saving_available"],
            simple_assumptions,
        )

    if edit_hits >= 1:
        path_reasons.append("edit-oriented wording → Cursor SDK coding run")
        return PathAdvice("cursor_sdk", path_reasons, 0.6, edit_codes, edit_assumptions)

    # Default for Cursor Agent mode callers: keep SDK, but note uncertainty.
    path_reasons.append(
        "ambiguous objective; defaulting to Cursor SDK only if workspace edits are needed"
    )
    path_reasons.append(
        "for simple Q&A, switch to Quick Question (local Ollama) to avoid paid Cursor spend"
    )
    return PathAdvice("cursor_sdk", path_reasons, 0.45, [], [])


def _cursor_routing_receipt(
    advice: PathAdvice,
    *,
    model_id: str | None,
    model_tier: str | None,
    alternatives: list[CursorRouteAlternative],
    explicit_selection: bool,
) -> RoutingDecisionReceipt:
    """Describe the Cursor path/model advice as a v1 recommendation stage.

    Static catalog + keyword heuristics only. When the recommended path is local
    Ollama the local model is unknown here, so `model` stays null.
    """
    if advice.path == "local_ollama":
        recommended = RoutingTarget(
            path="local_ollama",
            tier="local",
            provider="ollama",
        )
    else:
        recommended = RoutingTarget(
            path="cursor_sdk",
            tier=model_tier if model_tier in {"cheap", "balanced", "premium"} else None,
            provider="cursor-sdk",
            model=model_id,
        )

    routing_alternatives: list[RoutingAlternative] = []
    if advice.path == "local_ollama":
        # The local path is only recommended when no repository-edit signal was
        # found, so a paid coding agent is not an applicable alternative here.
        # Naming one would invent a justification the heuristics never made.
        pass
    else:
        recommended_rank = tier_rank(recommended.tier)
        for alternative in alternatives:
            rank = tier_rank(alternative.momihelm_tier)
            if rank is None or recommended_rank is None:
                continue
            kind = "cheaper" if rank < recommended_rank else "stronger" if rank > recommended_rank else None
            if kind is None or any(item.kind == kind for item in routing_alternatives):
                continue
            routing_alternatives.append(
                RoutingAlternative(
                    kind=kind,
                    target=RoutingTarget(
                        path="cursor_sdk",
                        tier=alternative.momihelm_tier,  # type: ignore[arg-type]
                        provider="cursor-sdk",
                        model=alternative.model_id,
                    ),
                    reason_codes=(
                        ["cost_saving_available"] if kind == "cheaper" else ["higher_risk_change"]
                    ),
                )
            )

    if not routing_alternatives:
        routing_alternatives.append(
            RoutingAlternative(kind="unavailable", reason_codes=["no_applicable_alternative"])
        )

    assumptions = [
        "no_historical_performance_data",
        "static_model_catalog",
        "heuristic_task_classification",
        "cursor_bridge_health_unknown",
        *advice.assumptions,
    ]
    return RoutingDecisionReceipt(
        recommended=recommended,
        basis="configured" if explicit_selection else "heuristic",
        reason_codes=dedupe(list(advice.reason_codes), REASON_CODES),  # type: ignore[arg-type]
        assumptions=dedupe(assumptions, ASSUMPTION_CODES),  # type: ignore[arg-type]
        confidence=RoutingConfidence(value=advice.confidence),
        alternatives=routing_alternatives,
        cost_efficiency=RoutingCostEfficiency(
            code=(
                "local_capability_sufficient"
                if advice.path == "local_ollama"
                else "paid_execution_justified"
            ),
        ),
    )


def recommend_cursor_route(req: CursorRouteRequest) -> CursorRouteRecommendation:
    advice = _recommend_execution_path(req)
    recommended_path, path_reasons, path_confidence = (
        advice.path,
        advice.reasons,
        advice.confidence,
    )

    requested = normalize_cursor_model_id(req.requested_model)
    if requested and requested != "auto" and not req.prefer_auto:
        model = get_cursor_model(requested)
        if model is not None:
            explicit_alternatives = _alternatives(model.id, req)
            return CursorRouteRecommendation(
                recommended_model_id=model.id,
                recommended_display_name=model.display_name,
                recommended_tier=model.momihelm_tier,
                route_class=model.route_class,
                reasons=[f"honoring explicit Cursor model selection: {model.display_name}"],
                alternatives=explicit_alternatives,
                recommended_path=recommended_path,
                path_reasons=path_reasons,
                recommendation_basis="heuristic",
                confidence=path_confidence,
                routing=_cursor_routing_receipt(
                    advice,
                    model_id=model.id,
                    model_tier=model.momihelm_tier,
                    alternatives=explicit_alternatives,
                    explicit_selection=True,
                ),
            )

    ranked: list[tuple[float, CursorModel, list[str]]] = []
    for model in _eligible_models(req.workflow):
        score, reasons = _score_model(
            model,
            complexity=req.complexity_level,
            policy_mode=req.policy_mode,
            workflow=req.workflow,
        )
        ranked.append((score, model, reasons))

    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked:
        fallback = get_cursor_model("composer-2.5-fast")
        assert fallback is not None
        return CursorRouteRecommendation(
            recommended_model_id=fallback.id,
            recommended_display_name=fallback.display_name,
            recommended_tier=fallback.momihelm_tier,
            route_class=fallback.route_class,
            reasons=["no eligible Cursor models; defaulting to Composer 2.5"],
            recommended_path=recommended_path,
            path_reasons=path_reasons,
            recommendation_basis="heuristic",
            confidence=path_confidence,
            routing=_cursor_routing_receipt(
                advice,
                model_id=fallback.id,
                model_tier=fallback.momihelm_tier,
                alternatives=[],
                explicit_selection=False,
            ),
        )

    best_score, best, best_reasons = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else None

    recommended_id = "auto" if req.prefer_auto else best.id
    recommended_display = "Auto" if req.prefer_auto else best.display_name
    ranked_alternatives = _alternatives(best.id, req, ranked[1:4])
    recommendation = CursorRouteRecommendation(
        recommended_model_id=recommended_id,
        recommended_display_name=recommended_display,
        recommended_tier=best.momihelm_tier,
        route_class=best.route_class,
        resolved_from_auto=req.prefer_auto,
        fallback_model_id=second.id if second else None,
        fallback_display_name=second.display_name if second else None,
        reasons=(
            [f"Auto resolves to {best.display_name} for this task"]
            if req.prefer_auto
            else best_reasons[:4]
        ),
        alternatives=ranked_alternatives,
        recommended_path=recommended_path,
        path_reasons=path_reasons,
        recommendation_basis="heuristic",
        confidence=path_confidence,
        routing=_cursor_routing_receipt(
            advice,
            model_id=recommended_id,
            model_tier=best.momihelm_tier,
            alternatives=ranked_alternatives,
            explicit_selection=False,
        ),
    )
    if req.prefer_auto:
        recommendation.reasons.append(
            f"auto score leader: {best.display_name} ({best_score:.2f})"
        )
    return recommendation


class CursorRunReceiptRequest(BaseModel):
    """Facts about one executed Cursor SDK run, for routing transparency."""

    objective: str = Field(min_length=1, max_length=100_000)
    task_type: str = Field(default="unknown", max_length=80)
    complexity_level: ComplexityLevel = "medium"
    policy_mode: PolicyMode = "balanced"
    workflow: WorkflowType = "agent"
    selected_model: str | None = Field(default=None, max_length=200)
    executed_model: str | None = Field(default=None, max_length=200)
    validation_command_provided: bool = False
    diff_requested: bool = False
    bridge_reachable: bool = False
    result_fingerprint: str | None = Field(default=None, max_length=128)
    diff_fingerprint: str | None = Field(default=None, max_length=128)


def _fingerprint(value: str | None) -> str | None:
    """Accept digests only. Anything with whitespace is rejected as content."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 128 or any(char.isspace() for char in text):
        return None
    return text


def _cursor_target(model_id: str | None) -> RoutingTarget:
    identifier = (model_id or "").strip() or None
    catalog_entry = get_cursor_model(identifier) if identifier else None
    return RoutingTarget(
        path="cursor_sdk",
        tier=catalog_entry.momihelm_tier if catalog_entry else None,  # type: ignore[arg-type]
        provider="cursor-sdk",
        model=identifier,
    )


def build_cursor_run_receipt(req: CursorRunReceiptRequest) -> RoutingDecisionReceipt:
    """Merge the server-side recommendation with observed SDK run facts.

    The recommendation is recomputed here from the objective and organization
    policy, so a client cannot claim a recommendation it never received.
    """
    recommendation = recommend_cursor_route(
        CursorRouteRequest(
            objective=req.objective,
            task_type=req.task_type,
            complexity_level=req.complexity_level,
            policy_mode=req.policy_mode,
            workflow=req.workflow,
        )
    )
    receipt = recommendation.routing.model_copy(deep=True)
    receipt.selected = _cursor_target(req.selected_model)
    receipt.executed = _cursor_target(req.executed_model)
    if receipt.executed.model is None:
        # The SDK did not report a model; do not assume the selected one ran.
        receipt.executed = RoutingTarget(path="cursor_sdk", provider="cursor-sdk")

    codes = list(receipt.reason_codes)
    if req.validation_command_provided:
        codes.append("validation_required")
    if req.diff_requested:
        codes.append("diff_capture_required")
    codes.extend(
        mismatch_reason_codes(receipt.recommended, receipt.selected, receipt.executed)
    )
    receipt.reason_codes = dedupe(codes, REASON_CODES)  # type: ignore[assignment]

    assumptions = [
        code
        for code in receipt.assumptions
        if not (req.bridge_reachable and code == "cursor_bridge_health_unknown")
    ]
    if req.bridge_reachable:
        assumptions.append("cursor_bridge_health_passed")
    if req.validation_command_provided:
        assumptions.append("validation_command_provided")
    receipt.assumptions = dedupe(assumptions, ASSUMPTION_CODES)  # type: ignore[assignment]

    if receipt.recommended.path == "local_ollama":
        # Local would have been enough for this objective; the paid run was a
        # user choice, not a MomiHelm recommendation.
        receipt.cost_efficiency.code = "local_capability_sufficient"
    else:
        receipt.cost_efficiency.code = "paid_execution_justified"

    receipt.fingerprints.result = _fingerprint(req.result_fingerprint)
    receipt.fingerprints.diff = _fingerprint(req.diff_fingerprint)
    return receipt


def _alternatives(
    selected_id: str,
    req: CursorRouteRequest,
    ranked: list[tuple[float, CursorModel, list[str]]] | None = None,
) -> list[CursorRouteAlternative]:
    if ranked is None:
        ranked = []
        for model in _eligible_models(req.workflow):
            if model.id == selected_id:
                continue
            score, reasons = _score_model(
                model,
                complexity=req.complexity_level,
                policy_mode=req.policy_mode,
                workflow=req.workflow,
            )
            ranked.append((score, model, reasons))
        ranked.sort(key=lambda item: item[0], reverse=True)

    alternatives: list[CursorRouteAlternative] = []
    for _, model, reasons in ranked:
        if model.id == selected_id:
            continue
        alternatives.append(
            CursorRouteAlternative(
                model_id=model.id,
                display_name=model.display_name,
                route_class=model.route_class,
                momihelm_tier=model.momihelm_tier,
                reason=reasons[0] if reasons else "alternative route",
            )
        )
        if len(alternatives) >= 3:
            break
    return alternatives


def compare_cursor_models(
    executed_model_id: str | None,
    recommended_model_id: str,
) -> dict:
    executed = get_cursor_model(executed_model_id)
    recommended = get_cursor_model(recommended_model_id)
    if recommended is None:
        recommended = get_cursor_model("composer-2.5-fast")
    if executed is None or recommended is None:
        return {
            "fit": "unknown",
            "executed_model_id": executed_model_id,
            "recommended_model_id": recommended.id if recommended else None,
        }

    tier_order = {"cheap": 0, "balanced": 1, "premium": 2}
    executed_tier = tier_order.get(executed.momihelm_tier, 1)
    recommended_tier = tier_order.get(recommended.momihelm_tier, 1)
    delta = executed_tier - recommended_tier
    if delta == 0:
        fit = "good_fit"
    elif delta > 0:
        fit = "overpowered"
    else:
        fit = "underpowered"

    return {
        "fit": fit,
        "executed_model_id": executed.id,
        "executed_display_name": executed.display_name,
        "recommended_model_id": recommended.id,
        "recommended_display_name": recommended.display_name,
        "executed_tier": executed.momihelm_tier,
        "recommended_tier": recommended.momihelm_tier,
    }
