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

CREATE INDEX IF NOT EXISTS idx_requests_created_at ON requests(created_at);
CREATE INDEX IF NOT EXISTS idx_requests_dept_id ON requests(dept_id);
CREATE INDEX IF NOT EXISTS idx_observability_exported ON observability_exports(exported);
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
    conn.execute("PRAGMA user_version = 2")


def get_db_path() -> str:
    return os.environ.get("USAGE_DB_PATH", DEFAULT_DB_PATH)


def init_db(db_path: str | None = None) -> None:
    path = db_path or get_db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA_SQL)
        _migrate_requests(conn)
        conn.commit()


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    init_db(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
