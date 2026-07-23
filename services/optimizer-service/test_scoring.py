"""Deterministic acceptance tests for Model Fit and Cost-to-Success."""

from __future__ import annotations

from usage.scoring import (
    BenchmarkEvidence,
    CandidateBenchmark,
    CostBenchmark,
    EvaluationOptions,
    PolicyAssessment,
    evaluate_session,
)
from usage.session_schemas import (
    CodingAttemptResponse,
    CodingSessionDetail,
    VerificationResponse,
)


def attempt(
    number: int,
    *,
    tier: str = "balanced",
    provider: str = "openai",
    actual_cost: float | None = 0.005,
    modeled_cost: float | None = None,
) -> CodingAttemptResponse:
    return CodingAttemptResponse(
        attempt_id=f"ca-{number}",
        session_id="cs-test",
        attempt_number=number,
        request_id=f"r-{number}",
        created_at=f"2026-07-22T10:0{number}:00",
        completed_at=f"2026-07-22T10:0{number}:10",
        executed_tier=tier,
        provider=provider,
        model=f"{provider}-model",
        recommended_workflow="debug",
        executed_workflow="debug",
        actual_api_cost=actual_cost,
        modeled_local_cost=modeled_cost,
        latency_ms=1000,
    )


def verification(
    verification_type: str,
    status: str,
    *,
    attempt_number: int | None = 1,
    source: str = "automated",
    score: float | None = None,
) -> VerificationResponse:
    return VerificationResponse(
        verification_id=(
            f"cv-{verification_type}-{status}-{attempt_number or 'session'}"
        ),
        session_id="cs-test",
        attempt_id=f"ca-{attempt_number}" if attempt_number else None,
        verification_type=verification_type,
        source=source,
        status=status,
        score=score,
        created_at="2026-07-22T10:03:00",
    )


def session(
    *,
    status: str,
    attempts: list[CodingAttemptResponse] | None = None,
    events: list[VerificationResponse] | None = None,
) -> CodingSessionDetail:
    return CodingSessionDetail(
        session_id="cs-test",
        organization_id="org-a",
        user_id="user-a",
        dept_id="engineering",
        policy_mode="balanced",
        objective_fingerprint="a" * 64,
        predicted_task_type="bug_fix",
        classification_confidence=0.9,
        classification_source="rules",
        classification_reason="bug-fix signal",
        clarification_required=False,
        complexity_level="medium",
        status=status,
        created_at="2026-07-22T10:00:00",
        updated_at="2026-07-22T10:04:00",
        completed_at=(
            "2026-07-22T10:04:00"
            if status in {"succeeded", "partially_succeeded", "failed"}
            else None
        ),
        attempts=attempts or [attempt(1)],
        verification_events=events or [],
    )


def approved_budget(amount: float = 0.005) -> CostBenchmark:
    return CostBenchmark(
        amount=amount,
        evidence=BenchmarkEvidence(
            source="organization_budget",
            reference_id="engineering-budget-v1",
            approved=True,
        ),
    )


def qualified_candidate(
    *,
    model_fit: float,
    cost: float,
    tier: str = "cheap",
    sample_size: int = 10,
) -> CandidateBenchmark:
    return CandidateBenchmark(
        candidate_id="candidate-cheap-plan",
        provider="openai",
        model="small-model",
        tier=tier,
        workflow="plan",
        model_fit=model_fit,
        cost_to_success=cost,
        policy_compliant=True,
        evidence=BenchmarkEvidence(
            source="organization_task_cohort",
            reference_id="bug-fix-python-cohort-v1",
            sample_size=sample_size,
            confidence="medium",
        ),
    )


PASSED_POLICY = PolicyAssessment(
    score=1,
    evidence=["attempt_1_input_guardrail_passed"],
    reason="All checks passed.",
)


def test_unverified_request_has_no_model_fit_or_cost_to_success():
    result = evaluate_session(
        session(status="unverified"),
        policy=PASSED_POLICY,
    )

    assert result.model_fit.status == "unavailable"
    assert result.model_fit.value is None
    assert result.cost_to_success.cost_spent == 0.005
    assert result.cost_to_success.cost_to_success is None
    assert result.fit_gap.status == "unavailable"


def test_verified_session_with_all_components_has_final_model_fit():
    result = evaluate_session(
        session(
            status="succeeded",
            events=[
                verification("tests", "passed"),
                verification(
                    "user_acceptance",
                    "passed",
                    source="user",
                ),
            ],
        ),
        policy=PASSED_POLICY,
        options=EvaluationOptions(cost_benchmark=approved_budget()),
    )

    assert result.model_fit.status == "final"
    assert result.model_fit.value == 100
    assert result.model_fit.confidence == "high"
    assert result.model_fit.missing_components == []
    assert result.cost_to_success.cost_to_success == 0.005
    assert result.cost_to_success.attempts_to_success == 1
    assert result.cost_to_success.time_to_success_ms == 240_000


def test_retry_costs_are_aggregated_and_observed_escalation_is_underpowered():
    result = evaluate_session(
        session(
            status="succeeded",
            attempts=[
                attempt(1, tier="cheap", actual_cost=0.002),
                attempt(2, tier="balanced", actual_cost=0.004),
            ],
            events=[
                verification("tests", "failed", attempt_number=1),
                verification("tests", "passed", attempt_number=2),
                verification(
                    "user_acceptance",
                    "passed",
                    attempt_number=2,
                    source="user",
                ),
            ],
        ),
        policy=PASSED_POLICY,
        options=EvaluationOptions(cost_benchmark=approved_budget(0.006)),
    )

    assert result.cost_to_success.cost_spent == 0.006
    assert result.cost_to_success.cost_to_success == 0.006
    assert result.cost_to_success.attempts_to_success == 2
    assert result.model_fit.components.attempt_efficiency == 0.5
    assert result.power_classification.status == "underpowered"


def test_failed_session_reports_spend_without_cost_to_success():
    result = evaluate_session(
        session(
            status="failed",
            events=[verification("tests", "failed")],
        ),
        policy=PASSED_POLICY,
        options=EvaluationOptions(cost_benchmark=approved_budget()),
    )

    assert result.model_fit.status == "provisional"
    assert result.model_fit.components.outcome == 0
    assert result.cost_to_success.cost_spent == 0.005
    assert result.cost_to_success.cost_to_success is None


def test_missing_cost_benchmark_is_disclosed_and_fit_gap_is_unavailable():
    result = evaluate_session(
        session(
            status="succeeded",
            events=[verification("tests", "passed")],
        ),
        policy=PASSED_POLICY,
    )

    assert result.model_fit.status == "provisional"
    assert result.model_fit.value is not None
    assert result.model_fit.missing_components == ["cost_efficiency"]
    assert result.fit_gap.status == "unavailable"


def test_unqualified_candidate_does_not_create_fit_gap():
    result = evaluate_session(
        session(
            status="succeeded",
            events=[verification("tests", "passed")],
        ),
        policy=PASSED_POLICY,
        options=EvaluationOptions(
            cost_benchmark=approved_budget(),
            candidates=[
                qualified_candidate(
                    model_fit=100,
                    cost=0.003,
                    sample_size=9,
                )
            ],
        ),
    )

    assert result.fit_gap.status == "unavailable"
    assert result.power_classification.status == "unavailable"


def test_qualified_cheaper_candidate_marks_session_overpowered():
    result = evaluate_session(
        session(
            status="succeeded",
            attempts=[attempt(1, actual_cost=0.01)],
            events=[verification("tests", "passed")],
        ),
        policy=PASSED_POLICY,
        options=EvaluationOptions(
            cost_benchmark=approved_budget(0.01),
            candidates=[qualified_candidate(model_fit=96, cost=0.007)],
        ),
    )

    assert result.model_fit.status == "final"
    assert result.fit_gap.status == "available"
    assert result.fit_gap.value == 0
    assert result.power_classification.status == "overpowered"


def test_failed_deterministic_check_overrides_claimed_success():
    result = evaluate_session(
        session(
            status="succeeded",
            events=[
                verification("build", "failed"),
                verification(
                    "offline_evaluator",
                    "passed",
                    source="evaluator",
                ),
            ],
        ),
        policy=PASSED_POLICY,
        options=EvaluationOptions(cost_benchmark=approved_budget()),
    )

    assert result.model_fit.components.outcome == 0
    assert result.model_fit.components.quality == 0


def test_local_execution_without_compute_rate_has_unknown_incomplete_cost():
    result = evaluate_session(
        session(
            status="succeeded",
            attempts=[
                attempt(
                    1,
                    tier="cheap",
                    provider="ollama",
                    actual_cost=0,
                    modeled_cost=None,
                )
            ],
            events=[verification("tests", "passed")],
        ),
        policy=PASSED_POLICY,
        options=EvaluationOptions(cost_benchmark=approved_budget()),
    )

    assert result.cost_to_success.cost_basis == "unknown"
    assert result.cost_to_success.complete is False
    assert result.cost_to_success.cost_to_success is None
    assert result.model_fit.status == "provisional"


def test_api_and_modeled_local_costs_produce_mixed_cost_basis():
    result = evaluate_session(
        session(
            status="succeeded",
            attempts=[
                attempt(1, tier="cheap", actual_cost=0.002),
                attempt(
                    2,
                    tier="balanced",
                    provider="ollama",
                    actual_cost=0,
                    modeled_cost=0.001,
                ),
            ],
            events=[verification("tests", "passed", attempt_number=2)],
        ),
        policy=PASSED_POLICY,
    )

    assert result.cost_to_success.cost_spent == 0.003
    assert result.cost_to_success.cost_basis == "mixed"


def test_policy_violation_cannot_produce_favorable_classification():
    result = evaluate_session(
        session(
            status="succeeded",
            attempts=[attempt(1, actual_cost=0.01)],
            events=[verification("tests", "passed")],
        ),
        policy=PolicyAssessment(
            score=0,
            evidence=["attempt_1_policy_violation"],
            reason="Policy violation.",
        ),
        options=EvaluationOptions(
            cost_benchmark=approved_budget(0.01),
            candidates=[qualified_candidate(model_fit=96, cost=0.007)],
        ),
    )

    assert result.power_classification.status == "unavailable"
    assert "Policy violations" in result.power_classification.reason
