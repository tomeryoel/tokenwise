"""Cursor local database path resolution."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def cursor_user_data_dir() -> Path:
    override = os.environ.get("CURSOR_USER_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()

    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library/Application Support/Cursor"
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return Path(appdata) / "Cursor"
        return home / "AppData/Roaming/Cursor"
    return home / ".config/Cursor"


def discover_state_databases() -> list[Path]:
    """Return Cursor state.vscdb files, newest workspace copies first."""
    user_dir = cursor_user_data_dir()
    candidates: list[Path] = []

    global_db = user_dir / "User/globalStorage/state.vscdb"
    if global_db.is_file():
        candidates.append(global_db)

    workspace_root = user_dir / "User/workspaceStorage"
    if workspace_root.is_dir():
        workspace_dbs = sorted(
            (
                path
                for path in workspace_root.glob("*/state.vscdb")
                if path.is_file()
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        candidates.extend(workspace_dbs)

    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            deduped.append(resolved)
    return deduped
