"""Acceptance tests for evidence-qualified Dashboard intelligence."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
from usage.database import init_db
from usage.intelligence_analytics import get_decision_intelligence_summary


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


def _timestamp(*, days_ago: int = 0) -> str:
    value = datetime.now(UTC) - timedelta(days=days_ago)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _insert_session(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    organization_id: str = "org-a",
    user_id: str = "user-a",
    dept_id: str = "engineering",
    task_type: str = "bug_fix",
    status: str = "succeeded",
    days_ago: int = 0,
    attempts: int = 1,
) -> None:
    created_at = _timestamp(days_ago=days_ago)
    conn.execute(
        """
        INSERT INTO coding_sessions (
            session_id, created_at, updated_at, completed_at,
            organization_id, user_id, dept_id, policy_mode,
            objective_fingerprint, predicted_task_type, confirmed_task_type,
            classification_confidence, classification_source,
            classification_reason, clarification_required, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'balanced', ?, ?, ?, 0.9,
                  'user', 'test classification', 0, ?)
        """,
        (
            session_id,
            created_at,
            created_at,
            created_at if status not in {"active", "unverified"} else None,
            organization_id,
            user_id,
            dept_id,
            f"fingerprint-{session_id}",
            task_type,
            task_type,
            status,
        ),
    )
    for attempt_number in range(1, attempts + 1):
        conn.execute(
            """
            INSERT INTO coding_attempts (
                attempt_id, session_id, attempt_number, created_at,
                completed_at, executed_tier, provider, model,
                recommended_workflow, executed_workflow,
                actual_api_cost, latency_ms
            ) VALUES (?, ?, ?, ?, ?, 'balanced', 'openai', 'test-model',
                      'plan', 'plan', 0.01, 1000)
            """,
            (
                f"attempt-{session_id}-{attempt_number}",
                session_id,
                attempt_number,
                created_at,
                created_at,
            ),
        )


def _insert_evaluation(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    suffix: str,
    model_fit_status: str,
    model_fit_value: float | None,
    confidence: str,
    cost_to_success: float | None,
    cost_basis: str,
    power: str,
) -> None:
    evaluation = {
        "session_id": session_id,
        "model_fit": {
            "status": model_fit_status,
            "value": model_fit_value,
        },
        "cost_to_success": {"cost_to_success": cost_to_success},
        "power_classification": {"status": power},
    }
    conn.execute(
        """
        INSERT INTO decision_evaluations (
            evaluation_id, session_id, scoring_version, facts_fingerprint,
            evaluation_options_json, model_fit_status, model_fit_value,
            evidence_confidence, cost_spent, cost_to_success, cost_basis,
            fit_gap_status, fit_gap_value, power_classification,
            evaluation_json, created_at
        ) VALUES (?, ?, 'model-fit-v1', ?, '{}', ?, ?, ?, 0.01, ?, ?,
                  'unavailable', NULL, ?, ?, ?)
        """,
        (
            f"evaluation-{session_id}-{suffix}",
            session_id,
            f"facts-{session_id}-{suffix}",
            model_fit_status,
            model_fit_value,
            confidence,
            cost_to_success,
            cost_basis,
            power,
            json.dumps(evaluation),
            _timestamp(),
        ),
    )


def _insert_automated_evidence(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute(
        """
        INSERT INTO verification_events (
            verification_id, session_id, verification_type,
            source, status, created_at
        ) VALUES (?, ?, 'tests', 'automated', 'passed', ?)
        """,
        (f"verification-{session_id}", session_id, _timestamp()),
    )


@pytest.fixture
def intelligence_db(tmp_db):
    with sqlite3.connect(tmp_db) as conn:
        _insert_session(conn, "session-one", attempts=2)
        _insert_evaluation(
            conn,
            "session-one",
            suffix="old",
            model_fit_status="provisional",
            model_fit_value=50,
            confidence="low",
            cost_to_success=None,
            cost_basis="unknown",
            power="unavailable",
        )
        _insert_evaluation(
            conn,
            "session-one",
            suffix="latest",
            model_fit_status="final",
            model_fit_value=90,
            confidence="high",
            cost_to_success=0.02,
            cost_basis="actual",
            power="appropriate",
        )
        _insert_automated_evidence(conn, "session-one")

        _insert_session(
            conn,
            "session-two",
            user_id="user-b",
            task_type="feature_implementation",
        )
        _insert_evaluation(
            conn,
            "session-two",
            suffix="latest",
            model_fit_status="final",
            model_fit_value=70,
            confidence="high",
            cost_to_success=0.01,
            cost_basis="actual",
            power="underpowered",
        )
        _insert_automated_evidence(conn, "session-two")

        _insert_session(
            conn,
            "session-three",
            dept_id="product",
            status="failed",
            attempts=1,
        )
        _insert_evaluation(
            conn,
            "session-three",
            suffix="latest",
            model_fit_status="provisional",
            model_fit_value=40,
            confidence="low",
            cost_to_success=None,
            cost_basis="actual",
            power="unavailable",
        )

        _insert_session(
            conn,
            "other-organization",
            organization_id="org-b",
            user_id="user-c",
        )
        _insert_evaluation(
            conn,
            "other-organization",
            suffix="latest",
            model_fit_status="final",
            model_fit_value=100,
            confidence="high",
            cost_to_success=0.001,
            cost_basis="actual",
            power="overpowered",
        )

        _insert_session(conn, "outside-period", days_ago=400)
        _insert_evaluation(
            conn,
            "outside-period",
            suffix="latest",
            model_fit_status="final",
            model_fit_value=100,
            confidence="high",
            cost_to_success=0.001,
            cost_basis="actual",
            power="overpowered",
        )
        conn.commit()
    return tmp_db


def test_empty_summary_is_honest_and_does_not_invent_zero_scores(tmp_db):
    summary = get_decision_intelligence_summary(
        organization_id="org-a",
        db_path=tmp_db,
    )

    assert summary.coverage.total_sessions == 0
    assert summary.model_fit.status == "unavailable"
    assert summary.model_fit.value is None
    assert summary.cost_to_success.status == "unavailable"
    assert summary.cost_to_success.value is None
    assert summary.top_recommendation is None


def test_summary_uses_latest_evaluation_and_discloses_coverage(intelligence_db):
    summary = get_decision_intelligence_summary(
        organization_id="org-a",
        period_days=30,
        db_path=intelligence_db,
    )

    assert summary.coverage.total_sessions == 3
    assert summary.coverage.terminal_sessions == 3
    assert summary.coverage.evaluated_sessions == 3
    assert summary.coverage.scored_sessions == 3
    assert summary.coverage.final_sessions == 2
    assert summary.coverage.provisional_sessions == 1
    assert summary.coverage.automated_evidence_sessions == 2
    assert summary.coverage.evidence_coverage_rate == pytest.approx(2 / 3, abs=0.001)
    assert summary.model_fit.status == "provisional"
    assert summary.model_fit.value == pytest.approx((90 + 70 + 40) / 3)
    assert summary.model_fit.sample_size == 3
    assert summary.cost_to_success.status == "qualified"
    assert summary.cost_to_success.value == pytest.approx(0.015)
    assert summary.cost_to_success.sample_size == 2
    assert summary.cost_to_success.eligible_sessions == 2
    assert summary.power.appropriate == 1
    assert summary.power.underpowered == 1
    assert summary.power.overpowered == 0
    assert summary.power.unavailable == 1
    assert summary.average_attempts_per_session == pytest.approx(4 / 3, abs=0.01)
    assert summary.top_recommendation is not None
    assert summary.top_recommendation.category == "underpowered_routing"
    assert summary.top_recommendation.evidence_status == "qualified"


def test_summary_breaks_down_task_types_without_exposing_objectives(intelligence_db):
    summary = get_decision_intelligence_summary(
        organization_id="org-a",
        db_path=intelligence_db,
    )
    payload = summary.model_dump()
    bug_fix = next(
        row for row in summary.task_types if row.task_type == "bug_fix"
    )

    assert bug_fix.sessions == 2
    assert bug_fix.successful_sessions == 1
    assert bug_fix.average_model_fit == 65
    assert "objective" not in json.dumps(payload)
    assert "fingerprint" not in json.dumps(payload)


def test_summary_enforces_user_department_and_period_scope(intelligence_db):
    member = get_decision_intelligence_summary(
        organization_id="org-a",
        user_id="user-a",
        db_path=intelligence_db,
    )
    product = get_decision_intelligence_summary(
        organization_id="org-a",
        dept_id="product",
        db_path=intelligence_db,
    )
    other_org = get_decision_intelligence_summary(
        organization_id="org-b",
        db_path=intelligence_db,
    )
    expanded_period = get_decision_intelligence_summary(
        organization_id="org-a",
        period_days=365,
        db_path=intelligence_db,
    )

    assert member.coverage.total_sessions == 2
    assert member.model_fit.value == 65
    assert product.coverage.total_sessions == 1
    assert product.model_fit.value == 40
    assert other_org.coverage.total_sessions == 1
    assert other_org.model_fit.value == 100
    assert expanded_period.coverage.total_sessions == 3


def test_active_evidence_does_not_inflate_terminal_coverage(tmp_db):
    with sqlite3.connect(tmp_db) as conn:
        _insert_session(conn, "active-session", status="active", attempts=3)
        _insert_automated_evidence(conn, "active-session")
        _insert_session(conn, "failed-without-evaluation", status="failed")
        conn.commit()

    summary = get_decision_intelligence_summary(
        organization_id="org-a",
        db_path=tmp_db,
    )

    assert summary.coverage.total_sessions == 2
    assert summary.coverage.terminal_sessions == 1
    assert summary.coverage.automated_evidence_sessions == 0
    assert summary.coverage.evidence_coverage_rate == 0
    assert summary.average_attempts_per_session == 1
    assert summary.top_recommendation is not None
    assert summary.top_recommendation.category == "outcome_coverage"
    assert summary.top_recommendation.affected_sessions == 1


def test_partial_outcome_is_not_eligible_for_cost_to_success(tmp_db):
    with sqlite3.connect(tmp_db) as conn:
        _insert_session(
            conn,
            "partial-session",
            status="partially_succeeded",
        )
        _insert_evaluation(
            conn,
            "partial-session",
            suffix="latest",
            model_fit_status="provisional",
            model_fit_value=72,
            confidence="low",
            cost_to_success=None,
            cost_basis="actual",
            power="unavailable",
        )
        conn.commit()

    summary = get_decision_intelligence_summary(
        organization_id="org-a",
        db_path=tmp_db,
    )

    assert summary.outcomes.partially_succeeded == 1
    assert summary.cost_to_success.eligible_sessions == 0
    assert summary.cost_to_success.value is None


def test_failed_session_cannot_enter_cost_to_success_from_stale_data(tmp_db):
    with sqlite3.connect(tmp_db) as conn:
        _insert_session(conn, "failed-session", status="failed")
        _insert_evaluation(
            conn,
            "failed-session",
            suffix="latest",
            model_fit_status="provisional",
            model_fit_value=35,
            confidence="low",
            cost_to_success=0.5,
            cost_basis="actual",
            power="unavailable",
        )
        conn.commit()

    summary = get_decision_intelligence_summary(
        organization_id="org-a",
        db_path=tmp_db,
    )

    assert summary.cost_to_success.eligible_sessions == 0
    assert summary.cost_to_success.sample_size == 0
    assert summary.cost_to_success.value is None
    assert summary.coverage.complete_cost_sessions == 0


def test_api_returns_scoped_intelligence_summary(tmp_path, monkeypatch):
    db_path = tmp_path / "usage.db"
    monkeypatch.setenv("USAGE_DB_PATH", str(db_path))
    with TestClient(app) as client:
        response = client.get(
            "/coding/analytics/summary",
            params={
                "organization_id": "org-a",
                "user_id": "user-a",
                "period_days": 7,
            },
        )

    assert response.status_code == 200
    assert response.json()["period_days"] == 7
    assert response.json()["coverage"]["total_sessions"] == 0
