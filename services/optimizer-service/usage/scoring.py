"""Pure, versioned scoring for coding-session decision intelligence."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from usage.session_schemas import CodingSessionDetail, VerificationResponse


SCORING_VERSION = "model-fit-v1"

EvidenceConfidence = Literal["insufficient", "low", "medium", "high"]
BenchmarkSource = Literal[
    "controlled_evaluation",
    "organization_task_cohort",
    "organization_benchmark",
    "organization_budget",
]

DETERMINISTIC_TYPES = {
    "tests",
    "build",
    "lint",
    "type_check",
    "static_analysis",
}
ACCEPTANCE_TYPES = {"user_acceptance", "connector_completion"}
EVALUATOR_TYPES = {"reviewer_assessment", "offline_evaluator"}
COMPONENT_WEIGHTS = {
    "outcome": 0.40,
    "quality": 0.25,
    "cost_efficiency": 0.15,
    "attempt_efficiency": 0.10,
    "policy": 0.10,
}
TIER_STRENGTH = {"local": 0, "cheap": 1, "balanced": 2, "premium": 3}


class ScoringModel(BaseModel):
    model_config = ConfigDict(protected_namespaces=())


class BenchmarkEvidence(ScoringModel):
    source: BenchmarkSource
    reference_id: str = Field(min_length=1, max_length=200)
    sample_size: int = Field(default=0, ge=0)
    confidence: EvidenceConfidence = "insufficient"
    approved: bool = False


class CostBenchmark(ScoringModel):
    amount: float = Field(ge=0, allow_inf_nan=False)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    evidence: BenchmarkEvidence


class CandidateBenchmark(ScoringModel):
    candidate_id: str = Field(min_length=1, max_length=200)
    provider: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=200)
    tier: str | None = Field(default=None, max_length=40)
    workflow: str | None = Field(default=None, max_length=40)
    model_fit: float = Field(ge=0, le=100, allow_inf_nan=False)
    cost_to_success: float = Field(ge=0, allow_inf_nan=False)
    policy_compliant: bool
    scoring_version: str = SCORING_VERSION
    evidence: BenchmarkEvidence


class EvaluationOptions(ScoringModel):
    cost_benchmark: CostBenchmark | None = None
    candidates: list[CandidateBenchmark] = Field(default_factory=list, max_length=100)
    local_compute_rate_version: str | None = Field(default=None, max_length=100)
    currency: str = Field(default="USD", min_length=3, max_length=3)


class PolicyAssessment(ScoringModel):
    score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    evidence: list[str] = Field(default_factory=list)
    reason: str


class ModelFitComponents(ScoringModel):
    outcome: float | None = None
    quality: float | None = None
    cost_efficiency: float | None = None
    attempt_efficiency: float | None = None
    policy: float | None = None


class ModelFitResult(ScoringModel):
    status: Literal["unavailable", "provisional", "final"]
    value: float | None = None
    confidence: EvidenceConfidence
    components: ModelFitComponents
    missing_components: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    basis: str
    reason: str


class CostToSuccessResult(ScoringModel):
    cost_spent: float
    cost_to_success: float | None = None
    attempts_to_success: int | None = None
    time_to_success_ms: int | None = None
    cost_basis: Literal["actual", "modeled", "mixed", "unknown"]
    local_compute_rate_version: str | None = None
    currency: str = "USD"
    complete: bool
    missing_cost_fields: list[str] = Field(default_factory=list)
    reason: str


class FitGapResult(ScoringModel):
    status: Literal["unavailable", "available"]
    value: float | None = None
    candidate_id: str | None = None
    basis: str | None = None
    reason: str


class PowerClassificationResult(ScoringModel):
    status: Literal[
        "unavailable",
        "appropriate",
        "overpowered",
        "underpowered",
    ]
    candidate_id: str | None = None
    confidence: EvidenceConfidence
    reason: str


class DecisionEvaluation(ScoringModel):
    session_id: str
    scoring_version: str = SCORING_VERSION
    model_fit: ModelFitResult
    cost_to_success: CostToSuccessResult
    fit_gap: FitGapResult
    power_classification: PowerClassificationResult
    evidence_sources: list[str] = Field(default_factory=list)


class DecisionEvaluationResponse(DecisionEvaluation):
    evaluation_id: str
    evaluated_at: str


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _event_value(event: VerificationResponse) -> float | None:
    if event.status == "skipped":
        return None
    if event.status == "failed":
        return 0.0
    if event.score is not None:
        return float(event.score)
    if event.status == "partial":
        return 0.5
    return 1.0


def _event_label(event: VerificationResponse) -> str:
    return f"{event.verification_type}_{event.status}"


def _is_deterministic(event: VerificationResponse) -> bool:
    return (
        event.verification_type in DETERMINISTIC_TYPES
        and event.source in {"automated", "connector"}
    )


def _is_user_feedback(event: VerificationResponse) -> bool:
    return event.source == "user" or event.verification_type == "user_acceptance"


def _outcome_events(session: CodingSessionDetail) -> list[VerificationResponse]:
    if not session.attempts:
        return list(session.verification_events)
    final_attempt_id = session.attempts[-1].attempt_id
    return [
        event
        for event in session.verification_events
        if event.attempt_id in {None, final_attempt_id}
    ]


def _evidence_confidence(
    events: list[VerificationResponse],
) -> EvidenceConfidence:
    usable = [event for event in events if event.status != "skipped"]
    has_deterministic = any(_is_deterministic(event) for event in usable)
    has_acceptance = any(
        event.verification_type in ACCEPTANCE_TYPES for event in usable
    )
    has_evaluator = any(
        event.verification_type in EVALUATOR_TYPES for event in usable
    )
    if has_deterministic and has_acceptance:
        return "high"
    if has_deterministic or (has_acceptance and has_evaluator):
        return "medium"
    if (
        has_acceptance
        or has_evaluator
        or any(_is_user_feedback(event) for event in usable)
    ):
        return "low"
    return "insufficient"


def _outcome_and_quality(
    session: CodingSessionDetail,
) -> tuple[float | None, float | None, EvidenceConfidence, list[str]]:
    events = _outcome_events(session)
    usable = [event for event in events if _event_value(event) is not None]
    evidence = [_event_label(event) for event in usable]
    confidence = _evidence_confidence(events)
    if session.status not in {"succeeded", "partially_succeeded", "failed"}:
        return None, None, confidence, evidence
    if not usable:
        return None, None, "insufficient", evidence

    deterministic = [
        event
        for event in usable
        if _is_deterministic(event)
    ]
    softer = [
        event
        for event in usable
        if (
            _is_user_feedback(event)
            or event.verification_type in ACCEPTANCE_TYPES | EVALUATOR_TYPES
        )
    ]
    quality_events = deterministic or softer
    quality_values = [
        value
        for event in quality_events
        if (value := _event_value(event)) is not None
    ]
    quality = (
        round(sum(quality_values) / len(quality_values), 6)
        if quality_values
        else None
    )

    blocking_failure = any(
        event.status == "failed"
        and (
            _is_deterministic(event)
            or _is_user_feedback(event)
            or event.verification_type in ACCEPTANCE_TYPES
        )
        for event in usable
    ) or any(
        event.verification_type == "rollback" and event.status == "passed"
        for event in usable
    )
    if session.status == "failed" or blocking_failure:
        outcome = 0.0
    elif session.status == "partially_succeeded":
        outcome = 0.5
    else:
        outcome = 1.0
    return outcome, quality, confidence, evidence


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _cost_result(
    session: CodingSessionDetail,
    options: EvaluationOptions,
) -> CostToSuccessResult:
    total = 0.0
    actual_known = False
    modeled_known = False
    actual_total = 0.0
    missing: list[str] = []

    for attempt in session.attempts:
        if attempt.actual_api_cost is not None:
            total += attempt.actual_api_cost
            actual_total += attempt.actual_api_cost
            actual_known = True
        if attempt.modeled_local_cost is not None:
            total += attempt.modeled_local_cost
            modeled_known = True

        provider = (attempt.provider or "").lower()
        tier = (attempt.executed_tier or "").lower()
        is_local = provider == "ollama" or tier == "local"
        if is_local and attempt.modeled_local_cost is None:
            missing.append(f"attempt_{attempt.attempt_number}_modeled_local_cost")
        elif not is_local and attempt.actual_api_cost is None:
            missing.append(f"attempt_{attempt.attempt_number}_actual_api_cost")

    missing_local_cost = any(
        field.endswith("_modeled_local_cost") for field in missing
    )
    if missing_local_cost and not modeled_known:
        basis = "unknown"
    elif modeled_known and actual_total > 0:
        basis = "mixed"
    elif modeled_known:
        basis = "modeled"
    elif actual_known:
        basis = "actual"
    else:
        basis = "unknown"

    complete = bool(session.attempts) and not missing and basis != "unknown"
    successful = session.status == "succeeded"
    started = _parse_datetime(session.created_at)
    completed = _parse_datetime(session.completed_at)
    elapsed_ms = None
    if successful and started is not None and completed is not None:
        elapsed_ms = max(0, int((completed - started).total_seconds() * 1000))

    cost_to_success = round(total, 12) if successful and complete else None
    if not session.attempts:
        reason = "No coding attempts have been recorded."
    elif not complete:
        reason = "Known spend is reported, but total cost is incomplete."
    elif not successful:
        reason = "Cost spent is available; Cost-to-Success requires verified success."
    else:
        reason = "All recorded attempts through verified success are included."

    return CostToSuccessResult(
        cost_spent=round(total, 12),
        cost_to_success=cost_to_success,
        attempts_to_success=len(session.attempts) if successful else None,
        time_to_success_ms=elapsed_ms,
        cost_basis=basis,
        local_compute_rate_version=options.local_compute_rate_version,
        currency=options.currency.upper(),
        complete=complete,
        missing_cost_fields=_unique(missing),
        reason=reason,
    )


def _benchmark_qualified(evidence: BenchmarkEvidence) -> bool:
    if evidence.source == "controlled_evaluation":
        return evidence.sample_size >= 2 and evidence.confidence in {"medium", "high"}
    if evidence.source == "organization_task_cohort":
        return evidence.sample_size >= 10 and evidence.confidence in {"medium", "high"}
    if evidence.source in {"organization_benchmark", "organization_budget"}:
        return evidence.approved
    return False


def _cost_efficiency(
    cost: CostToSuccessResult,
    benchmark: CostBenchmark | None,
) -> tuple[float | None, str | None]:
    if cost.cost_to_success is None or benchmark is None:
        return None, None
    if benchmark.currency.upper() != cost.currency:
        return None, None
    if not _benchmark_qualified(benchmark.evidence):
        return None, None
    if cost.cost_to_success == 0:
        score = 1.0
    elif benchmark.amount == 0:
        score = 0.0
    else:
        score = min(1.0, benchmark.amount / cost.cost_to_success)
    return round(score, 6), benchmark.evidence.reference_id


def _attempt_efficiency(
    session: CodingSessionDetail,
    outcome: float | None,
) -> float | None:
    if outcome is None or not session.attempts:
        return None
    if outcome == 0:
        return 0.0
    return round(1.0 / len(session.attempts), 6)


def _model_fit(
    session: CodingSessionDetail,
    *,
    cost: CostToSuccessResult,
    policy: PolicyAssessment,
    options: EvaluationOptions,
) -> ModelFitResult:
    outcome, quality, confidence, evidence = _outcome_and_quality(session)
    cost_efficiency, cost_basis = _cost_efficiency(
        cost,
        options.cost_benchmark,
    )
    components = ModelFitComponents(
        outcome=outcome,
        quality=quality,
        cost_efficiency=cost_efficiency,
        attempt_efficiency=_attempt_efficiency(session, outcome),
        policy=policy.score,
    )
    component_values = components.model_dump()
    missing = [
        name for name, value in component_values.items() if value is None
    ]
    all_evidence = _unique([*evidence, *policy.evidence])

    if outcome is None:
        return ModelFitResult(
            status="unavailable",
            confidence=confidence,
            components=components,
            missing_components=missing,
            evidence=all_evidence,
            basis="outcome_evidence_required",
            reason="Model Fit is unavailable until the coding outcome is verified.",
        )

    available_weight = sum(
        COMPONENT_WEIGHTS[name]
        for name, value in component_values.items()
        if value is not None
    )
    weighted_score = sum(
        COMPONENT_WEIGHTS[name] * value
        for name, value in component_values.items()
        if value is not None
    )
    value = round(100 * weighted_score / available_weight, 1)
    final = not missing and confidence in {"medium", "high"}
    if final:
        basis = cost_basis or "all_components"
        reason = "All five components and sufficient outcome evidence are available."
    else:
        basis = cost_basis or "available_components_cold_start"
        reason = (
            "The score uses only disclosed available components and is not final."
        )
    return ModelFitResult(
        status="final" if final else "provisional",
        value=value,
        confidence=confidence,
        components=components,
        missing_components=missing,
        evidence=all_evidence,
        basis=basis,
        reason=reason,
    )


def _qualified_candidates(
    candidates: list[CandidateBenchmark],
) -> list[CandidateBenchmark]:
    return [
        candidate
        for candidate in candidates
        if candidate.policy_compliant
        and candidate.evidence.source != "organization_budget"
        and candidate.scoring_version == SCORING_VERSION
        and _benchmark_qualified(candidate.evidence)
    ]


def _fit_gap(
    model_fit: ModelFitResult,
    candidates: list[CandidateBenchmark],
) -> FitGapResult:
    if model_fit.status != "final" or model_fit.value is None:
        return FitGapResult(
            status="unavailable",
            reason="Fit Gap requires a final actual Model Fit score.",
        )
    qualified = _qualified_candidates(candidates)
    if not qualified:
        return FitGapResult(
            status="unavailable",
            reason="No evidence-qualified comparison candidate is available.",
        )
    best = max(qualified, key=lambda candidate: candidate.model_fit)
    return FitGapResult(
        status="available",
        value=round(max(0.0, best.model_fit - model_fit.value), 1),
        candidate_id=best.candidate_id,
        basis=best.evidence.reference_id,
        reason="Compared with the best evidence-qualified compliant candidate.",
    )


def _attempt_failed(
    attempt_id: str,
    events: list[VerificationResponse],
) -> bool:
    return any(
        event.attempt_id == attempt_id
        and (
            (
                event.status == "failed"
                and (
                    _is_deterministic(event)
                    or _is_user_feedback(event)
                    or event.verification_type in ACCEPTANCE_TYPES
                )
            )
            or (
                event.verification_type == "rollback"
                and event.status == "passed"
            )
        )
        for event in events
    )


def _attempt_succeeded(
    attempt_id: str,
    events: list[VerificationResponse],
) -> bool:
    relevant = [
        event
        for event in events
        if event.attempt_id in {None, attempt_id}
        and event.status != "skipped"
    ]
    if not relevant:
        return False
    if any(
        event.status == "failed"
        and (
            _is_deterministic(event)
            or _is_user_feedback(event)
            or event.verification_type in ACCEPTANCE_TYPES
        )
        for event in relevant
    ):
        return False
    return any(event.status == "passed" for event in relevant)


def _observed_escalation(
    session: CodingSessionDetail,
) -> tuple[bool, str]:
    if session.status != "succeeded" or len(session.attempts) < 2:
        return False, ""
    first = session.attempts[0]
    final = session.attempts[-1]
    first_tier = TIER_STRENGTH.get((first.executed_tier or "").lower())
    final_tier = TIER_STRENGTH.get((final.executed_tier or "").lower())
    if first_tier is None or final_tier is None or final_tier <= first_tier:
        return False, ""
    if not _attempt_failed(first.attempt_id, session.verification_events):
        return False, ""
    if not _attempt_succeeded(final.attempt_id, session.verification_events):
        return False, ""
    return (
        True,
        f"The {first.executed_tier} initial route failed before "
        f"the stronger {final.executed_tier} route succeeded.",
    )


def _power_classification(
    session: CodingSessionDetail,
    *,
    model_fit: ModelFitResult,
    cost: CostToSuccessResult,
    candidates: list[CandidateBenchmark],
    policy: PolicyAssessment,
) -> PowerClassificationResult:
    if policy.score == 0:
        return PowerClassificationResult(
            status="unavailable",
            confidence=model_fit.confidence,
            reason="Policy violations cannot produce a favorable classification.",
        )
    escalated, escalation_reason = _observed_escalation(session)
    if escalated:
        return PowerClassificationResult(
            status="underpowered",
            confidence=model_fit.confidence,
            reason=escalation_reason,
        )

    if (
        model_fit.status != "final"
        or model_fit.value is None
        or cost.cost_to_success is None
    ):
        return PowerClassificationResult(
            status="unavailable",
            confidence=model_fit.confidence,
            reason="Power classification requires verified fit and cost evidence.",
        )

    qualified = _qualified_candidates(candidates)
    overpowered = [
        candidate
        for candidate in qualified
        if candidate.model_fit >= model_fit.value - 5
        and candidate.cost_to_success <= cost.cost_to_success * 0.8
    ]
    if overpowered:
        best = min(overpowered, key=lambda candidate: candidate.cost_to_success)
        return PowerClassificationResult(
            status="overpowered",
            candidate_id=best.candidate_id,
            confidence=model_fit.confidence,
            reason=(
                "A qualified compliant candidate has comparable fit at least "
                "20% lower Cost-to-Success."
            ),
        )

    actual_tier = (
        (session.attempts[-1].executed_tier or "").lower()
        if session.attempts
        else ""
    )
    actual_strength = TIER_STRENGTH.get(actual_tier)
    underpowered = [
        candidate
        for candidate in qualified
        if candidate.model_fit >= model_fit.value + 10
        and actual_strength is not None
        and TIER_STRENGTH.get((candidate.tier or "").lower(), -1)
        > actual_strength
    ]
    if underpowered:
        best = max(underpowered, key=lambda candidate: candidate.model_fit)
        return PowerClassificationResult(
            status="underpowered",
            candidate_id=best.candidate_id,
            confidence=model_fit.confidence,
            reason=(
                "A qualified stronger candidate exceeds actual Model Fit by "
                "at least 10 points."
            ),
        )

    if qualified:
        return PowerClassificationResult(
            status="appropriate",
            confidence=model_fit.confidence,
            reason="Qualified comparisons do not show overpowered or underpowered use.",
        )
    return PowerClassificationResult(
        status="unavailable",
        confidence=model_fit.confidence,
        reason="No evidence-qualified comparison candidate is available.",
    )


def evaluate_session(
    session: CodingSessionDetail,
    *,
    policy: PolicyAssessment,
    options: EvaluationOptions | None = None,
) -> DecisionEvaluation:
    """Evaluate one coding session without reading or writing external state."""
    evaluation_options = options or EvaluationOptions()
    cost = _cost_result(session, evaluation_options)
    model_fit = _model_fit(
        session,
        cost=cost,
        policy=policy,
        options=evaluation_options,
    )
    candidates = evaluation_options.candidates
    return DecisionEvaluation(
        session_id=session.session_id,
        model_fit=model_fit,
        cost_to_success=cost,
        fit_gap=_fit_gap(model_fit, candidates),
        power_classification=_power_classification(
            session,
            model_fit=model_fit,
            cost=cost,
            candidates=candidates,
            policy=policy,
        ),
        evidence_sources=_unique(model_fit.evidence),
    )
