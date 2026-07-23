"""SQLite identity, session, and organization-policy persistence."""

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


DEFAULT_DB_PATH = "/app/data/auth/momihelm-auth.db"
VALID_ROLES = {"owner", "admin", "member"}
VALID_POLICY_MODES = {"conservative", "balanced", "aggressive"}


@dataclass(frozen=True)
class Principal:
    id: str
    organization_id: str
    organization_name: str
    email: str
    display_name: str
    role: str
    department_id: str
    policy_mode: str

    @property
    def can_manage(self) -> bool:
        return self.role in {"owner", "admin"}


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    policy_mode TEXT NOT NULL DEFAULT 'balanced'
        CHECK (policy_mode IN ('conservative', 'balanced', 'aggressive')),
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'member')),
    department_id TEXT NOT NULL DEFAULT 'general',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_users_organization
    ON users(organization_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user
    ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry
    ON sessions(expires_at);
"""


def get_db_path() -> str:
    return os.environ.get("MOMIHELM_AUTH_DB_PATH", DEFAULT_DB_PATH)


def get_connection(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.executescript(SCHEMA_SQL)
    connection.execute("PRAGMA user_version = 1")
    connection.commit()
    return connection


def setup_required(db_path: str | None = None) -> bool:
    with get_connection(db_path) as connection:
        row = connection.execute("SELECT COUNT(*) AS total FROM users").fetchone()
    return int(row["total"]) == 0


def create_owner(
    *,
    email: str,
    display_name: str,
    organization_name: str,
    department_id: str,
    password_hash: str,
    db_path: str | None = None,
) -> Principal:
    now = int(time.time())
    organization_id = uuid.uuid4().hex
    user_id = uuid.uuid4().hex
    connection = get_connection(db_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute("SELECT COUNT(*) AS total FROM users").fetchone()
        if int(existing["total"]) != 0:
            raise ValueError("setup_already_completed")
        connection.execute(
            """
            INSERT INTO organizations (id, name, policy_mode, created_at)
            VALUES (?, ?, 'balanced', ?)
            """,
            (organization_id, organization_name, now),
        )
        connection.execute(
            """
            INSERT INTO users (
                id, organization_id, email, display_name, password_hash,
                role, department_id, is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, 'owner', ?, 1, ?)
            """,
            (
                user_id,
                organization_id,
                email,
                display_name,
                password_hash,
                department_id,
                now,
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    principal = get_user_by_id(user_id, db_path=db_path)
    if principal is None:
        raise RuntimeError("owner was not persisted")
    return principal


def create_user(
    *,
    organization_id: str,
    email: str,
    display_name: str,
    department_id: str,
    role: str,
    password_hash: str,
    db_path: str | None = None,
) -> Principal:
    if role not in VALID_ROLES:
        raise ValueError("invalid_role")
    now = int(time.time())
    user_id = uuid.uuid4().hex
    try:
        with get_connection(db_path) as connection:
            connection.execute(
                """
                INSERT INTO users (
                    id, organization_id, email, display_name, password_hash,
                    role, department_id, is_active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    user_id,
                    organization_id,
                    email,
                    display_name,
                    password_hash,
                    role,
                    department_id,
                    now,
                ),
            )
            connection.commit()
    except sqlite3.IntegrityError as exc:
        if "users.email" in str(exc):
            raise ValueError("email_already_exists") from exc
        raise
    principal = get_user_by_id(user_id, db_path=db_path)
    if principal is None:
        raise RuntimeError("user was not persisted")
    return principal


def list_users(
    organization_id: str,
    *,
    db_path: str | None = None,
) -> list[Principal]:
    with get_connection(db_path) as connection:
        rows = connection.execute(
            USER_SELECT
            + " AND u.organization_id = ? ORDER BY u.display_name COLLATE NOCASE",
            (organization_id,),
        ).fetchall()
    return [
        principal
        for row in rows
        if (principal := _principal_from_row(row)) is not None
    ]


def _principal_from_row(row: sqlite3.Row | None) -> Principal | None:
    if row is None:
        return None
    return Principal(
        id=row["id"],
        organization_id=row["organization_id"],
        organization_name=row["organization_name"],
        email=row["email"],
        display_name=row["display_name"],
        role=row["role"],
        department_id=row["department_id"],
        policy_mode=row["policy_mode"],
    )


USER_SELECT = """
SELECT
    u.id,
    u.organization_id,
    o.name AS organization_name,
    u.email,
    u.display_name,
    u.role,
    u.department_id,
    o.policy_mode
FROM users u
JOIN organizations o ON o.id = u.organization_id
WHERE u.is_active = 1
"""


def get_user_by_email(
    email: str,
    *,
    db_path: str | None = None,
) -> tuple[Principal, str] | None:
    with get_connection(db_path) as connection:
        row = connection.execute(
            USER_SELECT + " AND u.email = ? COLLATE NOCASE",
            (email,),
        ).fetchone()
        if row is None:
            return None
        principal = _principal_from_row(row)
        password_row = connection.execute(
            "SELECT password_hash FROM users WHERE id = ?",
            (row["id"],),
        ).fetchone()
    if principal is None or password_row is None:
        return None
    return principal, password_row["password_hash"]


def get_user_by_id(
    user_id: str,
    *,
    db_path: str | None = None,
) -> Principal | None:
    with get_connection(db_path) as connection:
        row = connection.execute(
            USER_SELECT + " AND u.id = ?",
            (user_id,),
        ).fetchone()
    return _principal_from_row(row)


def create_session(
    token_hash: str,
    user_id: str,
    *,
    ttl_seconds: int,
    db_path: str | None = None,
) -> None:
    now = int(time.time())
    with get_connection(db_path) as connection:
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        connection.execute(
            """
            INSERT INTO sessions (
                token_hash, user_id, created_at, expires_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (token_hash, user_id, now, now + ttl_seconds, now),
        )
        connection.commit()


def get_session_user(
    token_hash: str,
    *,
    db_path: str | None = None,
) -> Principal | None:
    now = int(time.time())
    with get_connection(db_path) as connection:
        row = connection.execute(
            """
            SELECT user_id
            FROM sessions
            WHERE token_hash = ? AND expires_at > ?
            """,
            (token_hash, now),
        ).fetchone()
        if row is None:
            return None
        connection.execute(
            "UPDATE sessions SET last_seen_at = ? WHERE token_hash = ?",
            (now, token_hash),
        )
        connection.commit()
    return get_user_by_id(row["user_id"], db_path=db_path)


def delete_session(token_hash: str, *, db_path: str | None = None) -> None:
    with get_connection(db_path) as connection:
        connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        connection.commit()


def update_password_and_revoke_sessions(
    user_id: str,
    password_hash: str,
    *,
    db_path: str | None = None,
) -> None:
    with get_connection(db_path) as connection:
        connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id),
        )
        connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        connection.commit()


def update_policy_mode(
    organization_id: str,
    policy_mode: str,
    *,
    db_path: str | None = None,
) -> None:
    if policy_mode not in VALID_POLICY_MODES:
        raise ValueError("invalid_policy_mode")
    with get_connection(db_path) as connection:
        connection.execute(
            "UPDATE organizations SET policy_mode = ? WHERE id = ?",
            (policy_mode, organization_id),
        )
        connection.commit()
