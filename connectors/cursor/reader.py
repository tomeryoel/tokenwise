"""Read-only access to Cursor state.vscdb key-value stores."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from connectors.cursor.paths import discover_state_databases


@dataclass(frozen=True)
class CursorKvEntry:
    database_path: Path
    table: str
    key: str
    value: str


@dataclass
class CursorDatabaseSnapshot:
    databases: list[Path] = field(default_factory=list)
    entries: dict[str, CursorKvEntry] = field(default_factory=dict)

    def get(self, key: str) -> CursorKvEntry | None:
        return self.entries.get(key)

    def keys_with_prefix(self, prefix: str) -> list[str]:
        return sorted(key for key in self.entries if key.startswith(prefix))


def _decode_value(raw: object) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _load_table(path: Path, table: str) -> list[tuple[str, str]]:
    uri = f"file:{path}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        cursor = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        if cursor.fetchone() is None:
            return []
        rows = connection.execute(f"SELECT key, value FROM {table}").fetchall()
    finally:
        connection.close()
    return [(str(key), _decode_value(value)) for key, value in rows]


def load_cursor_snapshot(
    database_paths: list[Path] | None = None,
) -> CursorDatabaseSnapshot:
    paths = database_paths or discover_state_databases()
    snapshot = CursorDatabaseSnapshot(databases=list(paths))

    for path in paths:
        for table in ("ItemTable", "cursorDiskKV"):
            for key, value in _load_table(path, table):
                snapshot.entries[key] = CursorKvEntry(
                    database_path=path,
                    table=table,
                    key=key,
                    value=value,
                )
    return snapshot


def load_json_entry(entry: CursorKvEntry | None) -> dict | list | None:
    if entry is None or not entry.value.strip():
        return None
    try:
        return json.loads(entry.value)
    except json.JSONDecodeError:
        return None
