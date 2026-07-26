"""Route coding tasks to the best Cursor model."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from cursor.models import CursorModel, get_cursor_model, load_cursor_models, normalize_cursor_model_id
from policy import PolicyMode


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


def _recommend_execution_path(
    req: CursorRouteRequest,
) -> tuple[Literal["local_ollama", "cursor_sdk"], list[str], float]:
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

    if needs_agent_workflow or edit_hits >= 2 or (edit_hits >= 1 and high_risk):
        path_reasons.append(
            "repository-edit / validation signals favor Cursor SDK coding run"
        )
        if high_risk:
            path_reasons.append("task type/complexity suggests stronger coding agent")
        return "cursor_sdk", path_reasons, 0.7

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
        return "local_ollama", path_reasons, 0.65

    if edit_hits == 0 and simple_hits >= 1 and req.complexity_level != "high":
        path_reasons.append(
            "explanation/summary-style objective without edit signals → prefer local Ollama"
        )
        return "local_ollama", path_reasons, 0.6

    if edit_hits >= 1:
        path_reasons.append("edit-oriented wording → Cursor SDK coding run")
        return "cursor_sdk", path_reasons, 0.6

    # Default for Cursor Agent mode callers: keep SDK, but note uncertainty.
    path_reasons.append(
        "ambiguous objective; defaulting to Cursor SDK only if workspace edits are needed"
    )
    path_reasons.append(
        "for simple Q&A, switch to Quick Question (local Ollama) to avoid paid Cursor spend"
    )
    return "cursor_sdk", path_reasons, 0.45


def recommend_cursor_route(req: CursorRouteRequest) -> CursorRouteRecommendation:
    recommended_path, path_reasons, path_confidence = _recommend_execution_path(req)

    requested = normalize_cursor_model_id(req.requested_model)
    if requested and requested != "auto" and not req.prefer_auto:
        model = get_cursor_model(requested)
        if model is not None:
            return CursorRouteRecommendation(
                recommended_model_id=model.id,
                recommended_display_name=model.display_name,
                recommended_tier=model.momihelm_tier,
                route_class=model.route_class,
                reasons=[f"honoring explicit Cursor model selection: {model.display_name}"],
                alternatives=_alternatives(model.id, req),
                recommended_path=recommended_path,
                path_reasons=path_reasons,
                recommendation_basis="heuristic",
                confidence=path_confidence,
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
        )

    best_score, best, best_reasons = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else None

    recommended_id = "auto" if req.prefer_auto else best.id
    recommended_display = "Auto" if req.prefer_auto else best.display_name
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
        alternatives=_alternatives(best.id, req, ranked[1:4]),
        recommended_path=recommended_path,
        path_reasons=path_reasons,
        recommendation_basis="heuristic",
        confidence=path_confidence,
    )
    if req.prefer_auto:
        recommendation.reasons.append(
            f"auto score leader: {best.display_name} ({best_score:.2f})"
        )
    return recommendation


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
