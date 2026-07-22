"""Persistence for idempotent Langfuse export attempts."""

from __future__ import annotations

from dataclasses import dataclass

from usage.database import get_connection


@dataclass(frozen=True)
class ExportRecord:
    request_id: str
    trace_id: str | None
    trace_url: str | None
    exported: bool
    attempt_count: int
    last_error: str | None


def get_export_record(request_id: str, db_path: str | None = None) -> ExportRecord | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT request_id, trace_id, trace_url, exported, attempt_count, last_error
            FROM observability_exports
            WHERE request_id = ?
            """,
            (request_id,),
        ).fetchone()
    if row is None:
        return None
    return ExportRecord(
        request_id=row["request_id"],
        trace_id=row["trace_id"],
        trace_url=row["trace_url"],
        exported=bool(row["exported"]),
        attempt_count=int(row["attempt_count"]),
        last_error=row["last_error"],
    )


def record_export_attempt(
    request_id: str,
    *,
    trace_id: str | None,
    trace_url: str | None,
    exported: bool,
    error: str | None,
    db_path: str | None = None,
) -> ExportRecord:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO observability_exports (
                request_id, trace_id, trace_url, exported, attempt_count,
                last_error, exported_at, updated_at
            ) VALUES (?, ?, ?, ?, 1, ?,
                CASE WHEN ? = 1 THEN datetime('now') ELSE NULL END,
                datetime('now'))
            ON CONFLICT(request_id) DO UPDATE SET
                trace_id = COALESCE(excluded.trace_id, observability_exports.trace_id),
                trace_url = COALESCE(excluded.trace_url, observability_exports.trace_url),
                exported = CASE
                    WHEN observability_exports.exported = 1 THEN 1
                    ELSE excluded.exported
                END,
                attempt_count = observability_exports.attempt_count + 1,
                last_error = CASE
                    WHEN excluded.exported = 1 THEN NULL
                    ELSE excluded.last_error
                END,
                exported_at = CASE
                    WHEN excluded.exported = 1 THEN datetime('now')
                    ELSE observability_exports.exported_at
                END,
                updated_at = datetime('now')
            """,
            (
                request_id,
                trace_id,
                trace_url,
                1 if exported else 0,
                error,
                1 if exported else 0,
            ),
        )
        conn.commit()
    record = get_export_record(request_id, db_path=db_path)
    if record is None:
        raise RuntimeError("Observability export record was not persisted")
    return record


def get_export_counts(db_path: str | None = None) -> dict[str, int]:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN exported = 1 THEN 1 ELSE 0 END) AS exported,
                SUM(CASE WHEN exported = 0 AND last_error IS NOT NULL THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN exported = 0 AND last_error IS NULL THEN 1 ELSE 0 END) AS pending
            FROM observability_exports
            """
        ).fetchone()
    return {
        "exported": int(row["exported"] or 0),
        "failed": int(row["failed"] or 0),
        "pending": int(row["pending"] or 0),
    }
