"""Tenant-scoped persistence for coding sessions and outcome evidence."""

from __future__ import annotations

import sqlite3
import uuid

from usage.coding_classifier import classify_coding_use_case
from usage.database import get_connection
from usage.repository import prompt_fingerprint
from usage.session_schemas import (
    CodingAttemptCreateRequest,
    CodingAttemptResponse,
    CodingSessionCreateRequest,
    CodingSessionDetail,
    CodingSessionListResponse,
    CodingSessionSummary,
    CodingSessionUpdateRequest,
    ContextSnapshotInput,
    ContextSnapshotResponse,
    VerificationCreateRequest,
    VerificationResponse,
)


ACTIVE_SESSION_STATUSES = {"active", "partially_succeeded", "unverified"}


class CodingSessionNotFoundError(LookupError):
    pass


class CodingSessionStateError(ValueError):
    pass


class CodingAttemptConflictError(ValueError):
    pass


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _session_scope(
    organization_id: str,
    user_id: str | None,
) -> tuple[str, list[object]]:
    clause = "organization_id = ?"
    params = [organization_id]
    if user_id is not None:
        clause += " AND user_id = ?"
        params.append(user_id)
    return clause, params


def _session_row(
    conn: sqlite3.Connection,
    session_id: str,
    organization_id: str,
    user_id: str | None,
) -> sqlite3.Row:
    scope, params = _session_scope(organization_id, user_id)
    row = conn.execute(
        f"SELECT * FROM coding_sessions WHERE session_id = ? AND {scope}",
        [session_id, *params],
    ).fetchone()
    if row is None:
        raise CodingSessionNotFoundError(session_id)
    return row


def _session_summary(row: sqlite3.Row) -> CodingSessionSummary:
    return CodingSessionSummary(
        session_id=row["session_id"],
        organization_id=row["organization_id"],
        user_id=row["user_id"],
        dept_id=row["dept_id"],
        policy_mode=row["policy_mode"],
        objective_fingerprint=row["objective_fingerprint"],
        predicted_task_type=row["predicted_task_type"],
        confirmed_task_type=row["confirmed_task_type"],
        classification_confidence=float(row["classification_confidence"]),
        classification_source=row["classification_source"],
        classification_reason=row["classification_reason"],
        clarification_required=bool(row["clarification_required"]),
        complexity_level=row["complexity_level"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
    )


def _context_response(row: sqlite3.Row | None) -> ContextSnapshotResponse | None:
    if row is None:
        return None
    return ContextSnapshotResponse(
        context_id=row["context_id"],
        attempt_id=row["attempt_id"],
        primary_language=row["primary_language"],
        repository_size=row["repository_size"],
        files_supplied=int(row["files_supplied"]),
        test_files_supplied=int(row["test_files_supplied"]),
        has_error_details=bool(row["has_error_details"]),
        has_acceptance_criteria=bool(row["has_acceptance_criteria"]),
        has_relevant_tests=bool(row["has_relevant_tests"]),
        approximate_context_tokens=int(row["approximate_context_tokens"]),
        context_source=row["context_source"],
        privacy_classification=row["privacy_classification"],
        created_at=row["created_at"],
    )


def _attempt_response(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
) -> CodingAttemptResponse:
    context_row = conn.execute(
        "SELECT * FROM context_snapshots WHERE attempt_id = ?",
        (row["attempt_id"],),
    ).fetchone()
    return CodingAttemptResponse(
        attempt_id=row["attempt_id"],
        session_id=row["session_id"],
        attempt_number=int(row["attempt_number"]),
        request_id=row["request_id"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
        recommended_tier=row["recommended_tier"],
        requested_tier=row["requested_tier"],
        executed_tier=row["executed_tier"],
        provider=row["provider"],
        model=row["model"],
        recommended_workflow=row["recommended_workflow"] or "unknown",
        executed_workflow=row["executed_workflow"] or "unknown",
        actual_api_cost=row["actual_api_cost"],
        modeled_local_cost=row["modeled_local_cost"],
        latency_ms=int(row["latency_ms"] or 0),
        context=_context_response(context_row),
    )


def _verification_response(row: sqlite3.Row) -> VerificationResponse:
    return VerificationResponse(
        verification_id=row["verification_id"],
        session_id=row["session_id"],
        attempt_id=row["attempt_id"],
        verification_type=row["verification_type"],
        source=row["source"],
        status=row["status"],
        score=row["score"],
        details=row["details"],
        created_at=row["created_at"],
    )


def create_coding_session(
    req: CodingSessionCreateRequest,
    db_path: str | None = None,
) -> CodingSessionDetail:
    classification = classify_coding_use_case(req.objective)
    session_id = _new_id("cs")
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO coding_sessions (
                session_id, organization_id, user_id, dept_id, policy_mode,
                objective_fingerprint, predicted_task_type,
                classification_confidence, classification_source,
                classification_reason, clarification_required, complexity_level
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'rules', ?, ?, ?)
            """,
            (
                session_id,
                req.organization_id,
                req.user_id,
                req.dept_id,
                req.policy_mode,
                prompt_fingerprint(req.objective),
                classification.task_type,
                classification.confidence,
                classification.reason,
                1 if classification.clarification_required else 0,
                req.complexity_level,
            ),
        )
        conn.commit()
    return get_coding_session(
        session_id,
        organization_id=req.organization_id,
        user_id=req.user_id,
        db_path=db_path,
    )


def list_coding_sessions(
    *,
    organization_id: str,
    user_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    db_path: str | None = None,
) -> CodingSessionListResponse:
    scope, params = _session_scope(organization_id, user_id)
    clauses = [scope]
    if status:
        clauses.append("status = ?")
        params.append(status)
    params.append(max(1, min(limit, 100)))
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM coding_sessions
            WHERE {' AND '.join(clauses)}
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    items = [_session_summary(row) for row in rows]
    return CodingSessionListResponse(items=items, count=len(items))


def get_coding_session(
    session_id: str,
    *,
    organization_id: str,
    user_id: str | None = None,
    db_path: str | None = None,
) -> CodingSessionDetail:
    with get_connection(db_path) as conn:
        session = _session_row(conn, session_id, organization_id, user_id)
        attempt_rows = conn.execute(
            """
            SELECT * FROM coding_attempts
            WHERE session_id = ?
            ORDER BY attempt_number
            """,
            (session_id,),
        ).fetchall()
        verification_rows = conn.execute(
            """
            SELECT * FROM verification_events
            WHERE session_id = ?
            ORDER BY created_at, verification_id
            """,
            (session_id,),
        ).fetchall()
        attempts = [_attempt_response(conn, row) for row in attempt_rows]
        verification_events = [
            _verification_response(row) for row in verification_rows
        ]
    return CodingSessionDetail(
        **_session_summary(session).model_dump(),
        attempts=attempts,
        verification_events=verification_events,
    )


def update_coding_session(
    session_id: str,
    req: CodingSessionUpdateRequest,
    *,
    organization_id: str,
    user_id: str,
    db_path: str | None = None,
) -> CodingSessionDetail:
    updates: list[str] = ["updated_at = datetime('now')"]
    params: list[str] = []
    if req.confirmed_task_type is not None:
        updates.extend(
            [
                "confirmed_task_type = ?",
                "classification_source = 'user'",
                "clarification_required = 0",
            ]
        )
        params.append(req.confirmed_task_type)
    if req.status is not None:
        updates.append("status = ?")
        params.append(req.status)
        if req.status == "active":
            updates.append("completed_at = NULL")
        else:
            updates.append("completed_at = datetime('now')")

    with get_connection(db_path) as conn:
        _session_row(conn, session_id, organization_id, user_id)
        conn.execute(
            f"""
            UPDATE coding_sessions
            SET {', '.join(updates)}
            WHERE session_id = ? AND organization_id = ? AND user_id = ?
            """,
            [*params, session_id, organization_id, user_id],
        )
        conn.commit()
    return get_coding_session(
        session_id,
        organization_id=organization_id,
        user_id=user_id,
        db_path=db_path,
    )


def _create_context(
    conn: sqlite3.Connection,
    attempt_id: str,
    context: ContextSnapshotInput,
) -> None:
    conn.execute(
        """
        INSERT INTO context_snapshots (
            context_id, attempt_id, primary_language, repository_size,
            files_supplied, test_files_supplied, has_error_details,
            has_acceptance_criteria, has_relevant_tests,
            approximate_context_tokens, context_source, privacy_classification
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _new_id("ctx"),
            attempt_id,
            context.primary_language,
            context.repository_size,
            context.files_supplied,
            context.test_files_supplied,
            1 if context.has_error_details else 0,
            1 if context.has_acceptance_criteria else 0,
            1 if context.has_relevant_tests else 0,
            context.approximate_context_tokens,
            context.context_source,
            context.privacy_classification,
        ),
    )


def add_coding_attempt(
    session_id: str,
    req: CodingAttemptCreateRequest,
    db_path: str | None = None,
) -> CodingAttemptResponse:
    with get_connection(db_path) as conn:
        session = _session_row(
            conn,
            session_id,
            req.organization_id,
            req.user_id,
        )
        if session["status"] not in ACTIVE_SESSION_STATUSES:
            raise CodingSessionStateError(
                f"cannot add an attempt to a {session['status']} session"
            )

        if req.request_id:
            existing = conn.execute(
                "SELECT * FROM coding_attempts WHERE request_id = ?",
                (req.request_id,),
            ).fetchone()
            if existing is not None:
                if existing["session_id"] != session_id:
                    raise CodingAttemptConflictError(
                        "request_id is already linked to another coding session"
                    )
                return _attempt_response(conn, existing)

        attempt_number = int(
            conn.execute(
                """
                SELECT COALESCE(MAX(attempt_number), 0) + 1
                FROM coding_attempts
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()[0]
        )
        attempt_id = _new_id("ca")
        try:
            conn.execute(
                """
                INSERT INTO coding_attempts (
                    attempt_id, session_id, attempt_number, request_id,
                    recommended_tier, requested_tier, executed_tier,
                    provider, model, recommended_workflow, executed_workflow,
                    actual_api_cost, modeled_local_cost, latency_ms,
                    completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    datetime('now'))
                """,
                (
                    attempt_id,
                    session_id,
                    attempt_number,
                    req.request_id,
                    req.recommended_tier,
                    req.requested_tier,
                    req.executed_tier,
                    req.provider,
                    req.model,
                    req.recommended_workflow,
                    req.executed_workflow,
                    req.actual_api_cost,
                    req.modeled_local_cost,
                    req.latency_ms,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise CodingAttemptConflictError("coding attempt already exists") from exc
        if req.context is not None:
            _create_context(conn, attempt_id, req.context)
        conn.execute(
            """
            UPDATE coding_sessions
            SET status = 'active',
                completed_at = NULL,
                updated_at = datetime('now')
            WHERE session_id = ?
            """,
            (session_id,),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM coding_attempts WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
        return _attempt_response(conn, row)


def add_verification_event(
    session_id: str,
    req: VerificationCreateRequest,
    db_path: str | None = None,
) -> VerificationResponse:
    verification_id = _new_id("cv")
    with get_connection(db_path) as conn:
        _session_row(conn, session_id, req.organization_id, req.user_id)
        if req.attempt_id is not None:
            attempt = conn.execute(
                """
                SELECT attempt_id FROM coding_attempts
                WHERE attempt_id = ? AND session_id = ?
                """,
                (req.attempt_id, session_id),
            ).fetchone()
            if attempt is None:
                raise CodingSessionNotFoundError(req.attempt_id)
        conn.execute(
            """
            INSERT INTO verification_events (
                verification_id, session_id, attempt_id, verification_type,
                source, status, score, details
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                verification_id,
                session_id,
                req.attempt_id,
                req.verification_type,
                req.source,
                req.status,
                req.score,
                req.details,
            ),
        )
        conn.execute(
            """
            UPDATE coding_sessions
            SET updated_at = datetime('now')
            WHERE session_id = ?
            """,
            (session_id,),
        )
        conn.commit()
        row = conn.execute(
            """
            SELECT * FROM verification_events
            WHERE verification_id = ?
            """,
            (verification_id,),
        ).fetchone()
    return _verification_response(row)
