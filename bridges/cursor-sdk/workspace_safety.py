"""Workspace safety helpers for the Cursor SDK coding-run bridge.

Uses only local Git and subprocess. Does not invent Cursor SDK APIs.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

BRIDGE_ROOT = Path(__file__).resolve().parent
FIXTURE_ROOT = BRIDGE_ROOT / "fixtures" / "coding-sandbox"
DEFAULT_SANDBOX_ROOT = BRIDGE_ROOT / "workspaces" / "coding-sandbox"

VALIDATION_ALLOWLIST = frozenset(
    {
        "npm test",
        "npm run test",
        "npm run lint",
        "pytest",
        "python -m pytest",
        "python3 -m pytest",
    }
)

MAX_DIFF_CHARS = 200_000
MAX_CHANGED_FILES = 200
GENERATED_DIR_NAMES = frozenset({"__pycache__", ".pytest_cache"})
GENERATED_SUFFIXES = (".pyc",)


@dataclass(frozen=True)
class GitPreflight:
    cwd: str
    is_git_repo: bool
    dirty: bool
    status_lines: list[str]
    block_reason: str | None


@dataclass(frozen=True)
class WorkspaceChangeReport:
    changed_files: list[str]
    diff_text: str | None
    diff_fingerprint: str | None
    diff_truncated: bool


@dataclass(frozen=True)
class ValidationReport:
    command: str
    status: str
    exit_code: int | None
    stdout: str
    stderr: str


def normalize_validation_command(command: str | None) -> str | None:
    if command is None:
        return None
    normalized = " ".join(command.split())
    return normalized or None


def validation_allowed(command: str | None) -> bool:
    normalized = normalize_validation_command(command)
    if not normalized:
        return True
    return normalized in VALIDATION_ALLOWLIST


def is_generated_path(path: str) -> bool:
    """Return True for Python cache / pytest cache paths that should not surface."""
    cleaned = path.strip().strip('"').replace("\\", "/")
    if cleaned.endswith("/"):
        cleaned = cleaned[:-1]
    parts = Path(cleaned).parts
    if any(part in GENERATED_DIR_NAMES for part in parts):
        return True
    return cleaned.endswith(GENERATED_SUFFIXES)


def ensure_disposable_sandbox(target: Path | None = None) -> Path:
    """Ensure a disposable sandbox git workspace exists for first coding runs."""
    sandbox = (target or DEFAULT_SANDBOX_ROOT).resolve()
    if not FIXTURE_ROOT.is_dir():
        raise FileNotFoundError(f"sandbox fixture missing: {FIXTURE_ROOT}")

    sandbox.parent.mkdir(parents=True, exist_ok=True)
    if not sandbox.exists():
        shutil.copytree(FIXTURE_ROOT, sandbox)
    elif not any(sandbox.iterdir()):
        shutil.copytree(FIXTURE_ROOT, sandbox, dirs_exist_ok=True)

    if not (sandbox / ".git").exists():
        _run_git(["init"], cwd=sandbox)
        _run_git(["config", "user.email", "sandbox@momihelm.local"], cwd=sandbox)
        _run_git(["config", "user.name", "MomiHelm Sandbox"], cwd=sandbox)
        _run_git(["add", "."], cwd=sandbox)
        _run_git(["commit", "-m", "Initial disposable sandbox"], cwd=sandbox)

    return sandbox


def reset_disposable_sandbox(target: Path | None = None) -> Path:
    """Recreate the disposable sandbox from the fixture (destroys local sandbox only)."""
    sandbox = (target or DEFAULT_SANDBOX_ROOT).resolve()
    if sandbox.exists():
        shutil.rmtree(sandbox)
    return ensure_disposable_sandbox(sandbox)


def git_preflight(cwd: str) -> GitPreflight:
    path = Path(cwd).expanduser().resolve()
    if not path.is_dir():
        return GitPreflight(
            cwd=str(path),
            is_git_repo=False,
            dirty=False,
            status_lines=[],
            block_reason="cwd_not_found",
        )

    probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return GitPreflight(
            cwd=str(path),
            is_git_repo=False,
            dirty=False,
            status_lines=[],
            block_reason="cwd_not_a_git_repository",
        )

    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        return GitPreflight(
            cwd=str(path),
            is_git_repo=True,
            dirty=True,
            status_lines=[],
            block_reason="git_status_failed",
        )

    lines = [
        line
        for line in status.stdout.splitlines()
        if line.strip() and not _status_line_is_generated(path, line)
    ]
    dirty = bool(lines)
    return GitPreflight(
        cwd=str(path),
        is_git_repo=True,
        dirty=dirty,
        status_lines=lines[:MAX_CHANGED_FILES],
        block_reason="dirty_git_worktree" if dirty else None,
    )


def collect_workspace_changes(cwd: str) -> WorkspaceChangeReport:
    path = Path(cwd).expanduser().resolve()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    files: list[str] = []
    if status.returncode == 0:
        for line in status.stdout.splitlines():
            if not line.strip() or _status_line_is_generated(path, line):
                continue
            entry = _status_path(line)
            if not entry or is_generated_path(entry) or _git_check_ignore(path, entry):
                continue
            files.append(entry)
            if len(files) >= MAX_CHANGED_FILES:
                break

    # Exclude generated paths from the user-facing diff as well.
    diff = subprocess.run(
        [
            "git",
            "diff",
            "HEAD",
            "--",
            ".",
            ":(exclude)__pycache__",
            ":(exclude)*/__pycache__/*",
            ":(exclude)*.pyc",
            ":(exclude).pytest_cache",
            ":(exclude)*/.pytest_cache/*",
        ],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    diff_text = diff.stdout if diff.returncode == 0 else ""
    truncated = False
    if len(diff_text) > MAX_DIFF_CHARS:
        diff_text = diff_text[:MAX_DIFF_CHARS]
        truncated = True

    fingerprint = None
    if diff_text or files:
        material = (diff_text + "\n" + "\n".join(files)).encode(
            "utf-8", errors="replace"
        )
        fingerprint = hashlib.sha256(material).hexdigest()

    return WorkspaceChangeReport(
        changed_files=files,
        diff_text=diff_text or None,
        diff_fingerprint=fingerprint,
        diff_truncated=truncated,
    )


def run_validation(cwd: str, command: str) -> ValidationReport:
    normalized = normalize_validation_command(command)
    if not normalized or not validation_allowed(normalized):
        return ValidationReport(
            command=command or "",
            status="rejected_not_allowlisted",
            exit_code=None,
            stdout="",
            stderr="validation_command_not_allowlisted",
        )

    completed = subprocess.run(
        normalized,
        cwd=Path(cwd).expanduser().resolve(),
        shell=True,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    return ValidationReport(
        command=normalized,
        status="passed" if completed.returncode == 0 else "failed",
        exit_code=completed.returncode,
        stdout=(completed.stdout or "")[:20_000],
        stderr=(completed.stderr or "")[:20_000],
    )


def _status_path(line: str) -> str:
    entry = line[3:] if len(line) > 3 else line
    if " -> " in entry:
        entry = entry.split(" -> ", 1)[1]
    return entry.strip().strip('"')


def _status_line_is_generated(cwd: Path, line: str) -> bool:
    entry = _status_path(line)
    if not entry:
        return False
    if is_generated_path(entry):
        return True
    return _git_check_ignore(cwd, entry)


def _git_check_ignore(cwd: Path, path: str) -> bool:
    completed = subprocess.run(
        ["git", "check-ignore", "-q", "--", path],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def _run_git(args: list[str], cwd: Path) -> None:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed in {cwd}: {completed.stderr.strip()}"
        )


def default_workspace_cwd() -> str:
    configured = os.environ.get("MOMIHELM_CURSOR_BRIDGE_CWD", "").strip()
    if configured:
        return str(Path(configured).expanduser().resolve())
    return str(ensure_disposable_sandbox())
