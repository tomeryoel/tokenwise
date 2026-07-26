"""Offline Cursor model routing (stdlib only) for hooks and MCP."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from connectors.cursor.models import normalize_cursor_model_id

CONFIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "optimizer-service"
    / "config"
    / "cursor_models.json"
)


@dataclass(frozen=True)
class RouteModel:
    id: str
    display_name: str
    family: str
    route_class: str
    momihelm_tier: str
    relative_cost: float
    relative_reasoning: float
    supports_agent: bool
    supports_plan: bool


@dataclass(frozen=True)
class RouteRecommendation:
    recommended_model_id: str
    recommended_display_name: str
    recommended_tier: str
    route_class: str
    resolved_from_auto: bool
    fallback_model_id: str | None
    fallback_display_name: str | None
    reasons: list[str]
    alternatives: list[dict]
    task_type: str
    complexity_level: str
    workflow: str

    def to_dict(self) -> dict:
        return {
            "recommended_model_id": self.recommended_model_id,
            "recommended_display_name": self.recommended_display_name,
            "recommended_tier": self.recommended_tier,
            "route_class": self.route_class,
            "resolved_from_auto": self.resolved_from_auto,
            "fallback_model_id": self.fallback_model_id,
            "fallback_display_name": self.fallback_display_name,
            "reasons": self.reasons,
            "alternatives": self.alternatives,
            "task_type": self.task_type,
            "complexity_level": self.complexity_level,
            "workflow": self.workflow,
        }

    def advisory_text(self) -> str:
        lines = [
            "MomiHelm Cursor route recommendation:",
            f"- Preferred model: {self.recommended_display_name} ({self.recommended_model_id})",
            f"- Tier: {self.recommended_tier} / class: {self.route_class}",
            f"- Task: {self.task_type} ({self.complexity_level}, workflow={self.workflow})",
        ]
        if self.fallback_display_name:
            lines.append(f"- Fallback: {self.fallback_display_name}")
        for reason in self.reasons[:3]:
            lines.append(f"- Why: {reason}")
        lines.append(
            "Select this model in Cursor when possible. Routing is advisory; "
            "Cursor still executes the model you choose."
        )
        return "\n".join(lines)


def _load_models() -> list[RouteModel]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    models: list[RouteModel] = []
    for item in payload.get("models", []):
        models.append(
            RouteModel(
                id=str(item["id"]),
                display_name=str(item["display_name"]),
                family=str(item.get("family", "unknown")),
                route_class=str(item.get("route_class", "balanced")),
                momihelm_tier=str(item.get("momihelm_tier", "balanced")),
                relative_cost=float(item.get("relative_cost", 0.5)),
                relative_reasoning=float(item.get("relative_reasoning", 0.5)),
                supports_agent=bool(item.get("supports_agent", True)),
                supports_plan=bool(item.get("supports_plan", True)),
            )
        )
    return models


def list_models() -> list[dict]:
    return [
        {
            "id": model.id,
            "display_name": model.display_name,
            "family": model.family,
            "route_class": model.route_class,
            "momihelm_tier": model.momihelm_tier,
            "relative_cost": model.relative_cost,
            "relative_reasoning": model.relative_reasoning,
        }
        for model in _load_models()
    ]


def _get(model_id: str | None) -> RouteModel | None:
    normalized = normalize_cursor_model_id(model_id) or model_id
    if not normalized:
        return None
    for model in _load_models():
        if model.id == normalized:
            return model
    return None


def infer_task_type(objective: str) -> str:
    text = re.sub(r"\s+", " ", (objective or "").strip().lower())
    rules = (
        ("test_generation", (r"\b(write|add|create|generate)\b.{0,24}\btests?\b",)),
        ("refactor", (r"\brefactor\b",)),
        ("architecture_design", (r"\barchitecture\b", r"\bdesign\b.{0,20}\bsystem\b")),
        ("bug_fix", (r"\bfix\b", r"\bbug\b", r"\berror\b")),
        ("feature_implementation", (r"\bimplement\b", r"\badd feature\b", r"\bbuild\b")),
        ("code_review", (r"\breview\b",)),
        ("documentation", (r"\bdocument\b", r"\breadme\b")),
    )
    for task_type, patterns in rules:
        for pattern in patterns:
            if re.search(pattern, text):
                return task_type
    return "unknown"


def infer_complexity(objective: str, task_type: str) -> str:
    text = (objective or "").lower()
    if task_type == "architecture_design" or len(text) > 400:
        return "high"
    if task_type in {"refactor", "documentation"} or len(text) < 80:
        return "low"
    return "medium"


def _score(
    model: RouteModel,
    *,
    complexity: str,
    policy_mode: str,
    workflow: str,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    complexity_target = {"low": 0.35, "medium": 0.6, "high": 0.85}.get(complexity, 0.6)
    reasoning_gap = abs(model.relative_reasoning - complexity_target)
    score += max(0.0, 1.0 - reasoning_gap) * 0.45
    reasons.append(
        f"{model.display_name} reasoning fit for {complexity} complexity"
    )

    if policy_mode == "conservative":
        score += (1.0 - model.relative_cost) * 0.35
        reasons.append("conservative policy favors lower-cost Cursor models")
    elif policy_mode == "aggressive":
        score += (1.0 - model.relative_cost) * 0.45
        reasons.append("aggressive policy prioritizes savings")
    else:
        score += (1.0 - abs(model.relative_cost - 0.45)) * 0.30
        reasons.append("balanced policy weighs cost and capability")

    if workflow == "agent" and model.supports_agent:
        score += 0.10
    if workflow == "plan" and model.supports_plan:
        score += 0.08
    if model.route_class == "economy" and complexity == "high":
        score -= 0.20
    if model.route_class == "premium" and complexity == "low":
        score -= 0.15
    return score, reasons


def recommend_route(
    *,
    objective: str,
    workflow: str = "agent",
    policy_mode: str = "balanced",
    requested_model: str | None = None,
    prefer_auto: bool = False,
    task_type: str | None = None,
    complexity_level: str | None = None,
) -> RouteRecommendation:
    task = task_type or infer_task_type(objective)
    complexity = complexity_level or infer_complexity(objective, task)
    workflow_norm = (workflow or "agent").lower()
    if workflow_norm in {"ask", "edit", "chat"}:
        workflow_norm = "direct"

    requested = normalize_cursor_model_id(requested_model)
    if requested and requested != "auto" and not prefer_auto:
        model = _get(requested)
        if model is not None:
            return RouteRecommendation(
                recommended_model_id=model.id,
                recommended_display_name=model.display_name,
                recommended_tier=model.momihelm_tier,
                route_class=model.route_class,
                resolved_from_auto=False,
                fallback_model_id=None,
                fallback_display_name=None,
                reasons=[f"honoring explicit Cursor model selection: {model.display_name}"],
                alternatives=[],
                task_type=task,
                complexity_level=complexity,
                workflow=workflow_norm,
            )

    ranked: list[tuple[float, RouteModel, list[str]]] = []
    for model in _load_models():
        if model.id == "auto":
            continue
        if workflow_norm == "agent" and not model.supports_agent:
            continue
        if workflow_norm == "plan" and not model.supports_plan:
            continue
        score, reasons = _score(
            model,
            complexity=complexity,
            policy_mode=policy_mode,
            workflow=workflow_norm,
        )
        ranked.append((score, model, reasons))
    ranked.sort(key=lambda item: item[0], reverse=True)

    if not ranked:
        fallback = _get("composer-2.5-fast")
        assert fallback is not None
        return RouteRecommendation(
            recommended_model_id=fallback.id,
            recommended_display_name=fallback.display_name,
            recommended_tier=fallback.momihelm_tier,
            route_class=fallback.route_class,
            resolved_from_auto=False,
            fallback_model_id=None,
            fallback_display_name=None,
            reasons=["no eligible Cursor models; defaulting to Composer 2.5"],
            alternatives=[],
            task_type=task,
            complexity_level=complexity,
            workflow=workflow_norm,
        )

    best_score, best, best_reasons = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else None
    alternatives = [
        {
            "model_id": model.id,
            "display_name": model.display_name,
            "route_class": model.route_class,
            "momihelm_tier": model.momihelm_tier,
            "reason": reasons[0] if reasons else "alternative",
        }
        for _, model, reasons in ranked[1:4]
    ]

    if prefer_auto:
        return RouteRecommendation(
            recommended_model_id="auto",
            recommended_display_name="Auto",
            recommended_tier=best.momihelm_tier,
            route_class=best.route_class,
            resolved_from_auto=True,
            fallback_model_id=second.id if second else None,
            fallback_display_name=second.display_name if second else None,
            reasons=[
                f"Auto resolves to {best.display_name} for this task",
                f"auto score leader: {best.display_name} ({best_score:.2f})",
            ],
            alternatives=alternatives,
            task_type=task,
            complexity_level=complexity,
            workflow=workflow_norm,
        )

    return RouteRecommendation(
        recommended_model_id=best.id,
        recommended_display_name=best.display_name,
        recommended_tier=best.momihelm_tier,
        route_class=best.route_class,
        resolved_from_auto=False,
        fallback_model_id=second.id if second else None,
        fallback_display_name=second.display_name if second else None,
        reasons=best_reasons[:4],
        alternatives=alternatives,
        task_type=task,
        complexity_level=complexity,
        workflow=workflow_norm,
    )


def compare_models(executed_model_id: str | None, recommended_model_id: str) -> dict:
    executed = _get(executed_model_id)
    recommended = _get(recommended_model_id) or _get("composer-2.5-fast")
    if executed is None or recommended is None:
        return {
            "fit": "unknown",
            "executed_model_id": executed_model_id,
            "recommended_model_id": recommended.id if recommended else None,
        }
    tier_order = {"cheap": 0, "balanced": 1, "premium": 2}
    delta = tier_order.get(executed.momihelm_tier, 1) - tier_order.get(
        recommended.momihelm_tier, 1
    )
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
