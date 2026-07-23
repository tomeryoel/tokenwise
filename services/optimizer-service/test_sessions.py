"""Coding-session persistence, isolation, classification, and API tests."""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from graph import run_optimizer
from main import app
from usage.coding_classifier import classify_coding_use_case
from usage.database import init_db
from usage.session_repository import (
    CodingSessionNotFoundError,
    CodingSessionStateError,
    add_coding_attempt,
    add_verification_event,
    create_coding_session,
    get_coding_session_evaluation,
    get_coding_session,
    list_coding_sessions,
    update_coding_session,
)
from usage.session_schemas import (
    CodingAttemptCreateRequest,
    CodingSessionCreateRequest,
    CodingSessionUpdateRequest,
    ContextSnapshotInput,
    VerificationCreateRequest,
)


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


@pytest.fixture
def api_client(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "usage.db"))
    with TestClient(app) as client:
        yield client


def session_request(
    *,
    organization_id: str = "org-a",
    user_id: str = "user-a",
    objective: str = "Fix the failing checkout test",
) -> CodingSessionCreateRequest:
    return CodingSessionCreateRequest(
        organization_id=organization_id,
        user_id=user_id,
        dept_id="engineering",
        policy_mode="balanced",
        objective=objective,
    )


def test_coding_ideation_phrase_is_not_unknown():
    result = classify_coding_use_case("I want you to code with me some game")
    assert result.task_type == "coding_ideation"
    assert result.clarification_required is True

    optimizer = run_optimizer(
        {
            "prompt": "I want you to code with me some game",
            "policy_mode": "balanced",
        }
    )
    assert optimizer["task_type"] == "code"


def test_session_stores_fingerprint_not_raw_objective(tmp_db):
    objective = "Fix the checkout bug without retaining this secret text"
    session = create_coding_session(
        session_request(objective=objective),
        db_path=tmp_db,
    )
    assert session.predicted_task_type == "bug_fix"
    assert len(session.objective_fingerprint) == 64

    with sqlite3.connect(tmp_db) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(coding_sessions)").fetchall()
        }
        stored = conn.execute(
            """
            SELECT objective_fingerprint
            FROM coding_sessions
            WHERE session_id = ?
            """,
            (session.session_id,),
        ).fetchone()[0]
    assert "objective" not in columns
    assert stored == session.objective_fingerprint
    assert objective not in stored


def test_session_listing_and_lookup_are_tenant_scoped(tmp_db):
    user_a = create_coding_session(session_request(), db_path=tmp_db)
    create_coding_session(
        session_request(user_id="user-b", objective="Review this code change"),
        db_path=tmp_db,
    )
    org_b = create_coding_session(
        session_request(
            organization_id="org-b",
            user_id="user-c",
            objective="Add unit tests",
        ),
        db_path=tmp_db,
    )

    manager = list_coding_sessions(
        organization_id="org-a",
        db_path=tmp_db,
    )
    member = list_coding_sessions(
        organization_id="org-a",
        user_id="user-a",
        db_path=tmp_db,
    )

    assert manager.count == 2
    assert member.count == 1
    assert member.items[0].session_id == user_a.session_id
    with pytest.raises(CodingSessionNotFoundError):
        get_coding_session(
            org_b.session_id,
            organization_id="org-a",
            db_path=tmp_db,
        )


def test_user_correction_preserves_original_prediction(tmp_db):
    session = create_coding_session(
        session_request(objective="Help me with a software task"),
        db_path=tmp_db,
    )
    assert session.predicted_task_type == "unknown"

    corrected = update_coding_session(
        session.session_id,
        CodingSessionUpdateRequest(confirmed_task_type="architecture_design"),
        organization_id="org-a",
        user_id="user-a",
        db_path=tmp_db,
    )
    assert corrected.predicted_task_type == "unknown"
    assert corrected.confirmed_task_type == "architecture_design"
    assert corrected.classification_source == "user"
    assert corrected.clarification_required is False


def test_attempts_are_numbered_idempotent_and_capture_context(tmp_db):
    session = create_coding_session(session_request(), db_path=tmp_db)
    first_request = CodingAttemptCreateRequest(
        organization_id="org-a",
        user_id="user-a",
        request_id="r-session-attempt",
        recommended_tier="balanced",
        requested_tier="balanced",
        executed_tier="cheap",
        provider="ollama",
        model="llama3.1:latest",
        recommended_workflow="debug",
        executed_workflow="direct",
        actual_api_cost=0,
        modeled_local_cost=0.0002,
        latency_ms=1200,
        context=ContextSnapshotInput(
            primary_language="Python",
            repository_size="medium",
            files_supplied=3,
            test_files_supplied=1,
            has_error_details=True,
            has_relevant_tests=True,
            approximate_context_tokens=900,
        ),
    )
    first = add_coding_attempt(session.session_id, first_request, db_path=tmp_db)
    duplicate = add_coding_attempt(session.session_id, first_request, db_path=tmp_db)
    second = add_coding_attempt(
        session.session_id,
        CodingAttemptCreateRequest(
            organization_id="org-a",
            user_id="user-a",
            request_id="r-session-attempt-2",
        ),
        db_path=tmp_db,
    )

    assert first.attempt_id == duplicate.attempt_id
    assert first.attempt_number == 1
    assert second.attempt_number == 2
    assert first.context is not None
    assert first.context.primary_language == "python"
    assert first.context.has_relevant_tests is True


def test_verification_lifecycle_and_terminal_session_protection(tmp_db):
    session = create_coding_session(session_request(), db_path=tmp_db)
    attempt = add_coding_attempt(
        session.session_id,
        CodingAttemptCreateRequest(
            organization_id="org-a",
            user_id="user-a",
            request_id="r-verified",
        ),
        db_path=tmp_db,
    )
    verification = add_verification_event(
        session.session_id,
        VerificationCreateRequest(
            organization_id="org-a",
            user_id="user-a",
            attempt_id=attempt.attempt_id,
            verification_type="tests",
            source="automated",
            status="passed",
            score=1,
        ),
        db_path=tmp_db,
    )
    completed = update_coding_session(
        session.session_id,
        CodingSessionUpdateRequest(status="succeeded"),
        organization_id="org-a",
        user_id="user-a",
        db_path=tmp_db,
    )

    assert verification.status == "passed"
    assert completed.status == "succeeded"
    assert completed.completed_at is not None
    assert len(completed.verification_events) == 1
    with pytest.raises(CodingSessionStateError):
        add_coding_attempt(
            session.session_id,
            CodingAttemptCreateRequest(
                organization_id="org-a",
                user_id="user-a",
            ),
            db_path=tmp_db,
        )


def test_new_attempt_reopens_an_unverified_session(tmp_db):
    session = create_coding_session(session_request(), db_path=tmp_db)
    update_coding_session(
        session.session_id,
        CodingSessionUpdateRequest(status="unverified"),
        organization_id="org-a",
        user_id="user-a",
        db_path=tmp_db,
    )

    add_coding_attempt(
        session.session_id,
        CodingAttemptCreateRequest(
            organization_id="org-a",
            user_id="user-a",
            request_id="r-reopened",
        ),
        db_path=tmp_db,
    )
    reopened = get_coding_session(
        session.session_id,
        organization_id="org-a",
        user_id="user-a",
        db_path=tmp_db,
    )

    assert reopened.status == "active"
    assert reopened.completed_at is None


def test_session_validation_rejects_empty_update_and_invalid_score():
    with pytest.raises(ValidationError):
        CodingSessionUpdateRequest()
    with pytest.raises(ValidationError):
        VerificationCreateRequest(
            organization_id="org-a",
            user_id="user-a",
            verification_type="tests",
            source="automated",
            status="passed",
            score=1.1,
        )


def test_internal_session_api_enforces_scope(api_client: TestClient):
    created = api_client.post(
        "/coding/sessions",
        json=session_request().model_dump(),
    )
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    owner_view = api_client.get(
        f"/coding/sessions/{session_id}",
        params={"organization_id": "org-a", "user_id": "user-a"},
    )
    cross_tenant = api_client.get(
        f"/coding/sessions/{session_id}",
        params={"organization_id": "org-b", "user_id": "user-a"},
    )
    corrected = api_client.patch(
        f"/coding/sessions/{session_id}",
        params={"organization_id": "org-a", "user_id": "user-a"},
        json={"confirmed_task_type": "bug_investigation"},
    )

    assert owner_view.status_code == 200
    assert cross_tenant.status_code == 404
    assert corrected.status_code == 200
    assert corrected.json()["confirmed_task_type"] == "bug_investigation"


def test_evaluation_is_versioned_cached_and_refreshed_with_new_evidence(tmp_db):
    created = create_coding_session(session_request(), db_path=tmp_db)
    attempt = add_coding_attempt(
        created.session_id,
        CodingAttemptCreateRequest(
            organization_id="org-a",
            user_id="user-a",
            request_id="r-evaluation",
            executed_tier="balanced",
            provider="openai",
            model="test-model",
            actual_api_cost=0.004,
        ),
        db_path=tmp_db,
    )
    add_verification_event(
        created.session_id,
        VerificationCreateRequest(
            organization_id="org-a",
            user_id="user-a",
            attempt_id=attempt.attempt_id,
            verification_type="tests",
            source="automated",
            status="passed",
        ),
        db_path=tmp_db,
    )
    update_coding_session(
        created.session_id,
        CodingSessionUpdateRequest(status="succeeded"),
        organization_id="org-a",
        user_id="user-a",
        db_path=tmp_db,
    )

    first = get_coding_session_evaluation(
        created.session_id,
        organization_id="org-a",
        user_id="user-a",
        db_path=tmp_db,
    )
    cached = get_coding_session_evaluation(
        created.session_id,
        organization_id="org-a",
        user_id="user-a",
        db_path=tmp_db,
    )
    assert first.evaluation_id == cached.evaluation_id
    assert first.scoring_version == "model-fit-v1"
    assert first.model_fit.status == "provisional"
    assert {"cost_efficiency", "policy"} <= set(
        first.model_fit.missing_components
    )

    add_verification_event(
        created.session_id,
        VerificationCreateRequest(
            organization_id="org-a",
            user_id="user-a",
            attempt_id=attempt.attempt_id,
            verification_type="user_acceptance",
            source="user",
            status="passed",
        ),
        db_path=tmp_db,
    )
    refreshed = get_coding_session_evaluation(
        created.session_id,
        organization_id="org-a",
        user_id="user-a",
        db_path=tmp_db,
    )

    assert refreshed.evaluation_id != first.evaluation_id
    assert refreshed.model_fit.confidence == "high"
    with sqlite3.connect(tmp_db) as conn:
        count = conn.execute(
            """
            SELECT COUNT(*) FROM decision_evaluations
            WHERE session_id = ?
            """,
            (created.session_id,),
        ).fetchone()[0]
    assert count == 2


def test_internal_evaluation_api_is_tenant_scoped(api_client: TestClient):
    created = api_client.post(
        "/coding/sessions",
        json=session_request().model_dump(),
    )
    session_id = created.json()["session_id"]

    owner = api_client.get(
        f"/coding/sessions/{session_id}/evaluation",
        params={"organization_id": "org-a", "user_id": "user-a"},
    )
    cross_tenant = api_client.get(
        f"/coding/sessions/{session_id}/evaluation",
        params={"organization_id": "org-b", "user_id": "user-a"},
    )

    assert owner.status_code == 200
    assert owner.json()["scoring_version"] == "model-fit-v1"
    assert owner.json()["model_fit"]["status"] == "unavailable"
    assert cross_tenant.status_code == 404
