"""Evidence-qualified aggregate analytics for coding decision intelligence."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from usage.database import get_connection


MetricStatus = Literal["unavailable", "provisional", "qualified"]
RecommendationPriority = Literal["low", "medium", "high"]
RecommendationEvidence = Literal["insufficient", "provisional", "qualified"]

CONFIDENCE_LEVELS = ("insufficient", "low", "medium", "high")
POWER_STATUSES = ("appropriate", "overpowered", "underpowered", "unavailable")
TERMINAL_STATUSES = {"succeeded", "partially_succeeded", "failed", "abandoned"}
SUCCESS_STATUSES = {"succeeded", "partially_succeeded"}
FULL_SUCCESS_STATUS = "succeeded"


class IntelligenceModel(BaseModel):
    model_config = ConfigDict(protected_namespaces=())


class IntelligenceMetric(IntelligenceModel):
    status: MetricStatus
    value: float | None = None
    sample_size: int = Field(ge=0)
    eligible_sessions: int = Field(ge=0)
    basis: str
    reason: str


class IntelligenceCoverage(IntelligenceModel):
    total_sessions: int = Field(ge=0)
    terminal_sessions: int = Field(ge=0)
    evaluated_sessions: int = Field(ge=0)
    scored_sessions: int = Field(ge=0)
    final_sessions: int = Field(ge=0)
    provisional_sessions: int = Field(ge=0)
    unavailable_sessions: int = Field(ge=0)
    automated_evidence_sessions: int = Field(ge=0)
    complete_cost_sessions: int = Field(ge=0)
    confidence_counts: dict[str, int]
    evidence_coverage_rate: float


class PowerSummary(IntelligenceModel):
    appropriate: int = Field(ge=0)
    overpowered: int = Field(ge=0)
    underpowered: int = Field(ge=0)
    unavailable: int = Field(ge=0)
    classified_sessions: int = Field(ge=0)
    coverage_rate: float


class OutcomeSummary(IntelligenceModel):
    active: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    partially_succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    abandoned: int = Field(ge=0)
    unverified: int = Field(ge=0)


class TaskTypeSummary(IntelligenceModel):
    task_type: str
    sessions: int = Field(ge=0)
    successful_sessions: int = Field(ge=0)
    scored_sessions: int = Field(ge=0)
    average_model_fit: float | None = None
    average_attempts: float


class TopRecommendation(IntelligenceModel):
    category: str
    priority: RecommendationPriority
    evidence_status: RecommendationEvidence
    title: str
    detail: str
    action: str
    affected_sessions: int = Field(ge=0)
    basis: str


class DecisionIntelligenceSummary(IntelligenceModel):
    period_days: int
    cohort_basis: Literal["coding_session_created_at"] = "coding_session_created_at"
    model_fit: IntelligenceMetric
    cost_to_success: IntelligenceMetric
    coverage: IntelligenceCoverage
    power: PowerSummary
    outcomes: OutcomeSummary
    average_attempts_per_session: float
    task_types: list[TaskTypeSummary]
    top_recommendation: TopRecommendation | None = None


def _scope_filter(
    *,
    period_days: int,
    organization_id: str,
    user_id: str | None,
    dept_id: str | None,
) -> tuple[str, list[object]]:
    clauses = [
        "datetime(s.created_at) >= datetime('now', ?)",
        "s.organization_id = ?",
    ]
    params: list[object] = [f"-{period_days} days", organization_id]
    if user_id is not None:
        clauses.append("s.user_id = ?")
        params.append(user_id)
    if dept_id is not None:
        clauses.append("s.dept_id = ?")
        params.append(dept_id)
    return " AND ".join(clauses), params


def _metric(
    *,
    values: list[float],
    eligible_sessions: int,
    qualified: bool,
    basis: str,
    unavailable_reason: str,
    available_reason: str,
) -> IntelligenceMetric:
    if not values:
        return IntelligenceMetric(
            status="unavailable",
            sample_size=0,
            eligible_sessions=eligible_sessions,
            basis=basis,
            reason=unavailable_reason,
        )
    return IntelligenceMetric(
        status="qualified" if qualified else "provisional",
        value=round(sum(values) / len(values), 6),
        sample_size=len(values),
        eligible_sessions=eligible_sessions,
        basis=basis,
        reason=available_reason,
    )


def _recommendation(
    *,
    rows: list,
    terminal_sessions: int,
    evaluated_sessions: int,
    scored_sessions: int,
    automated_evidence_sessions: int,
    complete_cost_sessions: int,
    power_counts: Counter,
    average_attempts: float,
) -> TopRecommendation | None:
    if not rows:
        return None

    underpowered_rows = [
        row for row in rows if row["power_classification"] == "underpowered"
    ]
    if underpowered_rows:
        qualified = any(row["model_fit_status"] == "final" for row in underpowered_rows)
        return TopRecommendation(
            category="underpowered_routing",
            priority="high",
            evidence_status="qualified" if qualified else "provisional",
            title="Strengthen routes that required escalation",
            detail=(
                f"{len(underpowered_rows)} session"
                f"{'' if len(underpowered_rows) == 1 else 's'} showed evidence that "
                "the original route was not strong enough."
            ),
            action=(
                "Review the affected task types and route similar work to the "
                "successful tier and workflow earlier."
            ),
            affected_sessions=len(underpowered_rows),
            basis="latest_power_classification_per_session",
        )

    overpowered = power_counts["overpowered"]
    if overpowered:
        return TopRecommendation(
            category="overpowered_routing",
            priority="high",
            evidence_status="qualified",
            title="Use simpler routes where fit remains comparable",
            detail=(
                f"{overpowered} session{'' if overpowered == 1 else 's'} had a "
                "qualified lower-cost comparison with comparable Model Fit."
            ),
            action=(
                "Adopt the qualified lower-cost candidate for matching use cases "
                "and continue monitoring outcome quality."
            ),
            affected_sessions=overpowered,
            basis="latest_power_classification_per_session",
        )

    missing_evaluations = max(0, terminal_sessions - evaluated_sessions)
    if missing_evaluations or (terminal_sessions and scored_sessions < terminal_sessions):
        affected = max(missing_evaluations, terminal_sessions - scored_sessions)
        return TopRecommendation(
            category="outcome_coverage",
            priority="high",
            evidence_status="insufficient",
            title="Complete outcome verification",
            detail=(
                f"{affected} completed session{'' if affected == 1 else 's'} "
                "cannot contribute a Model Fit score yet."
            ),
            action=(
                "Record whether the objective succeeded and attach the strongest "
                "available verification result."
            ),
            affected_sessions=affected,
            basis="terminal_sessions_without_scored_latest_evaluation",
        )

    missing_automation = max(0, terminal_sessions - automated_evidence_sessions)
    if missing_automation:
        return TopRecommendation(
            category="verification_quality",
            priority="medium",
            evidence_status="provisional",
            title="Add automated verification evidence",
            detail=(
                f"{missing_automation} completed session"
                f"{'' if missing_automation == 1 else 's'} rely on manual or "
                "incomplete verification."
            ),
            action=(
                "Connect tests, build, lint, or type-check results so Model Fit "
                "can move from provisional to evidence-qualified."
            ),
            affected_sessions=missing_automation,
            basis="terminal_sessions_without_automated_or_connector_evidence",
        )

    successful_sessions = sum(
        1 for row in rows if row["status"] == FULL_SUCCESS_STATUS
    )
    missing_cost = max(0, successful_sessions - complete_cost_sessions)
    if missing_cost:
        return TopRecommendation(
            category="cost_coverage",
            priority="medium",
            evidence_status="insufficient",
            title="Complete Cost-to-Success evidence",
            detail=(
                f"{missing_cost} successful session"
                f"{'' if missing_cost == 1 else 's'} lack complete execution cost."
            ),
            action=(
                "Configure a versioned local compute rate or provider pricing so "
                "successful local and external routes can be compared fairly."
            ),
            affected_sessions=missing_cost,
            basis="successful_sessions_without_complete_cost_to_success",
        )

    if power_counts["unavailable"]:
        return TopRecommendation(
            category="comparison_coverage",
            priority="medium",
            evidence_status="insufficient",
            title="Build qualified route comparisons",
            detail=(
                f"{power_counts['unavailable']} evaluated session"
                f"{'' if power_counts['unavailable'] == 1 else 's'} cannot yet be "
                "classified as appropriate, overpowered, or underpowered."
            ),
            action=(
                "Collect controlled or organization-cohort benchmarks for matching "
                "task types, models, workflows, and Cost-to-Success."
            ),
            affected_sessions=power_counts["unavailable"],
            basis="latest_power_classification_unavailable",
        )

    if average_attempts > 1.25:
        return TopRecommendation(
            category="attempt_efficiency",
            priority="low",
            evidence_status="qualified",
            title="Reduce repeat attempts",
            detail=(
                f"Sessions averaged {average_attempts:.1f} attempts in this period."
            ),
            action=(
                "Review context and workflow patterns for the task types with the "
                "highest retry counts."
            ),
            affected_sessions=len(rows),
            basis="coding_attempt_count_per_session",
        )

    return TopRecommendation(
        category="expand_sample",
        priority="low",
        evidence_status="qualified",
        title="Expand the verified sample",
        detail="Current evidence does not reveal a stronger routing correction.",
        action=(
            "Continue collecting verified sessions across additional task types "
            "before changing organization policy."
        ),
        affected_sessions=len(rows),
        basis="latest_evaluation_and_power_summary",
    )


def get_decision_intelligence_summary(
    *,
    organization_id: str,
    period_days: int = 30,
    user_id: str | None = None,
    dept_id: str | None = None,
    db_path: str | None = None,
) -> DecisionIntelligenceSummary:
    """Aggregate the latest evaluation for each privacy-scoped coding session."""

    period_days = max(1, min(period_days, 365))
    scope_clause, params = _scope_filter(
        period_days=period_days,
        organization_id=organization_id,
        user_id=user_id,
        dept_id=dept_id,
    )
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            WITH latest_evaluation_ids AS (
                SELECT session_id, MAX(rowid) AS evaluation_rowid
                FROM decision_evaluations
                GROUP BY session_id
            ),
            attempt_totals AS (
                SELECT session_id, COUNT(*) AS attempt_count
                FROM coding_attempts
                GROUP BY session_id
            ),
            automated_evidence AS (
                SELECT session_id, 1 AS has_automated_evidence
                FROM verification_events
                WHERE source IN ('automated', 'connector', 'evaluator')
                  AND status != 'skipped'
                GROUP BY session_id
            )
            SELECT
                s.session_id,
                s.status,
                COALESCE(s.confirmed_task_type, s.predicted_task_type) AS task_type,
                COALESCE(a.attempt_count, 0) AS attempt_count,
                COALESCE(v.has_automated_evidence, 0) AS has_automated_evidence,
                d.model_fit_status,
                d.model_fit_value,
                d.evidence_confidence,
                d.cost_to_success,
                d.cost_basis,
                d.power_classification
            FROM coding_sessions s
            LEFT JOIN latest_evaluation_ids latest
              ON latest.session_id = s.session_id
            LEFT JOIN decision_evaluations d
              ON d.rowid = latest.evaluation_rowid
            LEFT JOIN attempt_totals a ON a.session_id = s.session_id
            LEFT JOIN automated_evidence v ON v.session_id = s.session_id
            WHERE {scope_clause}
            ORDER BY s.created_at DESC, s.session_id
            """,
            params,
        ).fetchall()

    total_sessions = len(rows)
    terminal_sessions = sum(1 for row in rows if row["status"] in TERMINAL_STATUSES)
    terminal_rows = [
        row for row in rows if row["status"] in TERMINAL_STATUSES
    ]
    evaluated_rows = [
        row for row in terminal_rows if row["model_fit_status"] is not None
    ]
    scored_values = [
        float(row["model_fit_value"])
        for row in evaluated_rows
        if row["model_fit_value"] is not None
    ]
    final_sessions = sum(
        1 for row in evaluated_rows if row["model_fit_status"] == "final"
    )
    provisional_sessions = sum(
        1 for row in evaluated_rows if row["model_fit_status"] == "provisional"
    )
    unavailable_sessions = total_sessions - len(scored_values)
    terminal_evaluated_sessions = sum(
        1
        for row in evaluated_rows
        if row["status"] in TERMINAL_STATUSES
    )
    terminal_scored_sessions = sum(
        1
        for row in evaluated_rows
        if row["status"] in TERMINAL_STATUSES
        and row["model_fit_value"] is not None
    )
    automated_evidence_sessions = sum(
        1
        for row in rows
        if row["status"] in TERMINAL_STATUSES
        and row["has_automated_evidence"]
    )
    cost_values = [
        float(row["cost_to_success"])
        for row in evaluated_rows
        if row["status"] == FULL_SUCCESS_STATUS
        and row["cost_to_success"] is not None
    ]
    confidence_counts = Counter(
        row["evidence_confidence"] or "insufficient" for row in evaluated_rows
    )
    normalized_confidence_counts = {
        level: int(confidence_counts[level]) for level in CONFIDENCE_LEVELS
    }
    power_counts = Counter(
        row["power_classification"] or "unavailable" for row in rows
    )
    normalized_power_counts = {
        status: int(power_counts[status]) for status in POWER_STATUSES
    }
    classified_sessions = sum(
        normalized_power_counts[status]
        for status in ("appropriate", "overpowered", "underpowered")
    )
    outcome_counts = Counter(row["status"] for row in rows)
    average_attempts = (
        round(
            sum(int(row["attempt_count"]) for row in terminal_rows)
            / terminal_sessions,
            2,
        )
        if terminal_sessions
        else 0.0
    )

    task_rows: dict[str, list] = defaultdict(list)
    for row in rows:
        task_rows[row["task_type"] or "unknown"].append(row)
    task_types = []
    for task_type, group in task_rows.items():
        task_scores = [
            float(row["model_fit_value"])
            for row in group
            if row["model_fit_value"] is not None
        ]
        task_types.append(
            TaskTypeSummary(
                task_type=task_type,
                sessions=len(group),
                successful_sessions=sum(
                    1 for row in group if row["status"] in SUCCESS_STATUSES
                ),
                scored_sessions=len(task_scores),
                average_model_fit=(
                    round(sum(task_scores) / len(task_scores), 1)
                    if task_scores
                    else None
                ),
                average_attempts=round(
                    sum(int(row["attempt_count"]) for row in group) / len(group),
                    2,
                ),
            )
        )
    task_types.sort(key=lambda item: (-item.sessions, item.task_type))

    return DecisionIntelligenceSummary(
        period_days=period_days,
        model_fit=_metric(
            values=scored_values,
            eligible_sessions=terminal_sessions,
            qualified=bool(scored_values)
            and final_sessions == len(scored_values),
            basis="latest_model_fit_per_session_with_non_null_score",
            unavailable_reason=(
                "No session in this view has enough verified outcome evidence "
                "for a Model Fit score."
            ),
            available_reason=(
                "Average of each session's latest non-null Model Fit score; "
                "missing scores are excluded and disclosed in coverage."
            ),
        ),
        cost_to_success=_metric(
            values=cost_values,
            eligible_sessions=sum(
                1 for row in rows if row["status"] == FULL_SUCCESS_STATUS
            ),
            qualified=bool(cost_values),
            basis="latest_complete_cost_to_success_per_successful_session",
            unavailable_reason=(
                "No successful session has complete provider or modeled local "
                "execution cost."
            ),
            available_reason=(
                "Average only across successful sessions with complete "
                "Cost-to-Success evidence."
            ),
        ),
        coverage=IntelligenceCoverage(
            total_sessions=total_sessions,
            terminal_sessions=terminal_sessions,
            evaluated_sessions=len(evaluated_rows),
            scored_sessions=len(scored_values),
            final_sessions=final_sessions,
            provisional_sessions=provisional_sessions,
            unavailable_sessions=unavailable_sessions,
            automated_evidence_sessions=automated_evidence_sessions,
            complete_cost_sessions=len(cost_values),
            confidence_counts=normalized_confidence_counts,
            evidence_coverage_rate=(
                round(automated_evidence_sessions / terminal_sessions, 4)
                if terminal_sessions
                else 0.0
            ),
        ),
        power=PowerSummary(
            **normalized_power_counts,
            classified_sessions=classified_sessions,
            coverage_rate=(
                round(classified_sessions / total_sessions, 4)
                if total_sessions
                else 0.0
            ),
        ),
        outcomes=OutcomeSummary(
            active=int(outcome_counts["active"]),
            succeeded=int(outcome_counts["succeeded"]),
            partially_succeeded=int(outcome_counts["partially_succeeded"]),
            failed=int(outcome_counts["failed"]),
            abandoned=int(outcome_counts["abandoned"]),
            unverified=int(outcome_counts["unverified"]),
        ),
        average_attempts_per_session=average_attempts,
        task_types=task_types,
        top_recommendation=_recommendation(
            rows=terminal_rows,
            terminal_sessions=terminal_sessions,
            evaluated_sessions=terminal_evaluated_sessions,
            scored_sessions=terminal_scored_sessions,
            automated_evidence_sessions=automated_evidence_sessions,
            complete_cost_sessions=len(cost_values),
            power_counts=power_counts,
            average_attempts=average_attempts,
        ),
    )
