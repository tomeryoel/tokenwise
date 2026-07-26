"""SQLite database initialization and connection management."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = "/app/data/usage/tokenwise.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    organization_id TEXT NOT NULL DEFAULT 'legacy-local',
    user_id TEXT NOT NULL DEFAULT 'legacy-anonymous',
    dept_id TEXT NOT NULL DEFAULT 'unknown',
    policy_mode TEXT NOT NULL DEFAULT 'balanced',
    prompt_fingerprint TEXT NOT NULL,
    task_type TEXT,
    complexity_level TEXT,
    guardrail_status TEXT,
    guardrail_reason TEXT,
    detected_risk_type TEXT,
    cache_status TEXT,
    cache_confidence REAL,
    graph_path TEXT,
    status TEXT NOT NULL DEFAULT 'completed'
);

CREATE TABLE IF NOT EXISTS model_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL UNIQUE,
    provider TEXT,
    model TEXT,
    requested_tier TEXT,
    executed_tier TEXT,
    actual_input_tokens INTEGER DEFAULT 0,
    actual_output_tokens INTEGER DEFAULT 0,
    actual_total_tokens INTEGER DEFAULT 0,
    actual_cost REAL,
    cost_calculation_status TEXT,
    latency_ms INTEGER DEFAULT 0,
    used_fallback INTEGER DEFAULT 0,
    fallback_reason TEXT,
    privacy_enforced INTEGER DEFAULT 0,
    actual_execution_attempt_count INTEGER DEFAULT 0,
    FOREIGN KEY (request_id) REFERENCES requests(request_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS optimization_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL UNIQUE,
    action_type TEXT NOT NULL DEFAULT 'optimization',
    savings_source TEXT NOT NULL DEFAULT 'unknown',
    savings_reason TEXT,
    estimated_baseline_cost REAL DEFAULT 0,
    estimated_optimized_cost REAL DEFAULT 0,
    estimated_savings REAL DEFAULT 0,
    actual_cost_saved REAL,
    metadata_json TEXT,
    FOREIGN KEY (request_id) REFERENCES requests(request_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS output_guardrail_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL UNIQUE,
    status TEXT,
    issues_json TEXT,
    FOREIGN KEY (request_id) REFERENCES requests(request_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS observability_exports (
    request_id TEXT PRIMARY KEY,
    trace_id TEXT,
    trace_url TEXT,
    exported INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    exported_at TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (request_id) REFERENCES requests(request_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS coding_sessions (
    session_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    organization_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    dept_id TEXT NOT NULL,
    policy_mode TEXT NOT NULL DEFAULT 'balanced',
    objective_fingerprint TEXT NOT NULL,
    predicted_task_type TEXT NOT NULL,
    confirmed_task_type TEXT,
    classification_confidence REAL NOT NULL,
    classification_source TEXT NOT NULL DEFAULT 'rules',
    classification_reason TEXT NOT NULL,
    clarification_required INTEGER NOT NULL DEFAULT 0,
    complexity_level TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    external_source TEXT,
    external_session_id TEXT
);

CREATE TABLE IF NOT EXISTS coding_attempts (
    attempt_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    request_id TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    recommended_tier TEXT,
    requested_tier TEXT,
    executed_tier TEXT,
    provider TEXT,
    model TEXT,
    recommended_workflow TEXT,
    executed_workflow TEXT,
    actual_api_cost REAL,
    modeled_local_cost REAL,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    external_attempt_id TEXT,
    UNIQUE (session_id, attempt_number),
    FOREIGN KEY (session_id) REFERENCES coding_sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS context_snapshots (
    context_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL UNIQUE,
    primary_language TEXT,
    repository_size TEXT,
    files_supplied INTEGER NOT NULL DEFAULT 0,
    test_files_supplied INTEGER NOT NULL DEFAULT 0,
    has_error_details INTEGER NOT NULL DEFAULT 0,
    has_acceptance_criteria INTEGER NOT NULL DEFAULT 0,
    has_relevant_tests INTEGER NOT NULL DEFAULT 0,
    approximate_context_tokens INTEGER NOT NULL DEFAULT 0,
    context_source TEXT NOT NULL DEFAULT 'manual',
    privacy_classification TEXT NOT NULL DEFAULT 'standard',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (attempt_id) REFERENCES coding_attempts(attempt_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS verification_events (
    verification_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    attempt_id TEXT,
    verification_type TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    score REAL,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES coding_sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY (attempt_id) REFERENCES coding_attempts(attempt_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS decision_evaluations (
    evaluation_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    scoring_version TEXT NOT NULL,
    facts_fingerprint TEXT NOT NULL,
    evaluation_options_json TEXT NOT NULL,
    model_fit_status TEXT NOT NULL,
    model_fit_value REAL,
    evidence_confidence TEXT NOT NULL,
    cost_spent REAL NOT NULL,
    cost_to_success REAL,
    cost_basis TEXT NOT NULL,
    fit_gap_status TEXT NOT NULL,
    fit_gap_value REAL,
    power_classification TEXT NOT NULL,
    evaluation_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES coding_sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_requests_created_at ON requests(created_at);
CREATE INDEX IF NOT EXISTS idx_requests_dept_id ON requests(dept_id);
CREATE INDEX IF NOT EXISTS idx_observability_exported ON observability_exports(exported);
CREATE INDEX IF NOT EXISTS idx_coding_sessions_org
    ON coding_sessions(organization_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_coding_sessions_user
    ON coding_sessions(user_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_coding_sessions_status
    ON coding_sessions(status);
CREATE INDEX IF NOT EXISTS idx_coding_attempts_session
    ON coding_attempts(session_id, attempt_number);
CREATE INDEX IF NOT EXISTS idx_verification_events_session
    ON verification_events(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_decision_evaluations_session
    ON decision_evaluations(session_id, created_at);

CREATE TABLE IF NOT EXISTS cursor_ingest_events (
    event_key TEXT PRIMARY KEY,
    session_id TEXT,
    attempt_id TEXT,
    ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES coding_sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY (attempt_id) REFERENCES coding_attempts(attempt_id) ON DELETE CASCADE
);

-- External-id unique indexes are created by _migrate_coding_external_ids so
-- existing databases receive the columns before the indexes are applied.

CREATE TABLE IF NOT EXISTS cursor_sdk_runs (
    run_key TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    sdk_run_id TEXT,
    sdk_agent_id TEXT,
    selected_model TEXT,
    recommended_model TEXT,
    model_used TEXT,
    status TEXT NOT NULL,
    result_fingerprint TEXT,
    error_detail TEXT,
    duration_ms INTEGER,
    workspace_kind TEXT,
    changed_files_json TEXT,
    diff_fingerprint TEXT,
    validation_command TEXT,
    validation_status TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES coding_sessions(session_id) ON DELETE CASCADE,
    FOREIGN KEY (attempt_id) REFERENCES coding_attempts(attempt_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cursor_sdk_runs_session
    ON cursor_sdk_runs(session_id, created_at);
"""


def _migrate_requests(conn: sqlite3.Connection) -> None:
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(requests)").fetchall()
    }
    if "organization_id" not in columns:
        conn.execute(
            "ALTER TABLE requests ADD COLUMN organization_id "
            "TEXT NOT NULL DEFAULT 'legacy-local'"
        )
    if "user_id" not in columns:
        conn.execute(
            "ALTER TABLE requests ADD COLUMN user_id "
            "TEXT NOT NULL DEFAULT 'legacy-anonymous'"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_requests_organization_id "
        "ON requests(organization_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_requests_user_id ON requests(user_id)"
    )
    conn.execute("PRAGMA user_version = 4")


def _migrate_coding_external_ids(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 5:
        return

    session_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(coding_sessions)").fetchall()
    }
    if "external_source" not in session_columns:
        conn.execute("ALTER TABLE coding_sessions ADD COLUMN external_source TEXT")
    if "external_session_id" not in session_columns:
        conn.execute("ALTER TABLE coding_sessions ADD COLUMN external_session_id TEXT")

    attempt_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(coding_attempts)").fetchall()
    }
    if "external_attempt_id" not in attempt_columns:
        conn.execute("ALTER TABLE coding_attempts ADD COLUMN external_attempt_id TEXT")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cursor_ingest_events (
            event_key TEXT PRIMARY KEY,
            session_id TEXT,
            attempt_id TEXT,
            ingested_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (session_id) REFERENCES coding_sessions(session_id) ON DELETE CASCADE,
            FOREIGN KEY (attempt_id) REFERENCES coding_attempts(attempt_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_coding_sessions_external
        ON coding_sessions(external_source, external_session_id)
        WHERE external_session_id IS NOT NULL
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_coding_attempts_external
        ON coding_attempts(external_attempt_id)
        WHERE external_attempt_id IS NOT NULL
        """
    )
    conn.execute("PRAGMA user_version = 5")


def _migrate_cursor_sdk_runs(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 6:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cursor_sdk_runs (
            run_key TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            sdk_run_id TEXT,
            sdk_agent_id TEXT,
            selected_model TEXT,
            recommended_model TEXT,
            model_used TEXT,
            status TEXT NOT NULL,
            result_fingerprint TEXT,
            error_detail TEXT,
            duration_ms INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (session_id) REFERENCES coding_sessions(session_id) ON DELETE CASCADE,
            FOREIGN KEY (attempt_id) REFERENCES coding_attempts(attempt_id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_cursor_sdk_runs_session
        ON cursor_sdk_runs(session_id, created_at)
        """
    )
    conn.execute("PRAGMA user_version = 6")


def _migrate_cursor_sdk_coding_run_metadata(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 7:
        return
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(cursor_sdk_runs)").fetchall()
    }
    additions = {
        "workspace_kind": "TEXT",
        "changed_files_json": "TEXT",
        "diff_fingerprint": "TEXT",
        "validation_command": "TEXT",
        "validation_status": "TEXT",
    }
    for name, decl in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE cursor_sdk_runs ADD COLUMN {name} {decl}")
    conn.execute("PRAGMA user_version = 7")


def get_db_path() -> str:
    return os.environ.get("USAGE_DB_PATH", DEFAULT_DB_PATH)


def init_db(db_path: str | None = None) -> None:
    path = db_path or get_db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA_SQL)
        _migrate_requests(conn)
        _migrate_coding_external_ids(conn)
        _migrate_cursor_sdk_runs(conn)
        _migrate_cursor_sdk_coding_run_metadata(conn)
        conn.commit()


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    init_db(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
