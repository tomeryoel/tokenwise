from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from workspace_safety import (
    VALIDATION_ALLOWLIST,
    collect_workspace_changes,
    ensure_disposable_sandbox,
    git_preflight,
    normalize_validation_command,
    reset_disposable_sandbox,
    run_validation,
    validation_allowed,
)


def test_validation_allowlist_exact():
    assert "python -m pytest" in VALIDATION_ALLOWLIST
    assert validation_allowed("  npm   test  ")
    assert not validation_allowed("rm -rf /")
    assert normalize_validation_command("  pytest  ") == "pytest"


def test_ensure_and_preflight_clean_sandbox(tmp_path: Path):
    sandbox = ensure_disposable_sandbox(tmp_path / "coding-sandbox")
    report = git_preflight(str(sandbox))
    assert report.is_git_repo
    assert not report.dirty
    assert report.block_reason is None


def test_dirty_worktree_hard_block(tmp_path: Path):
    sandbox = ensure_disposable_sandbox(tmp_path / "coding-sandbox")
    (sandbox / "hello.py").write_text("print('dirty')\n", encoding="utf-8")
    report = git_preflight(str(sandbox))
    assert report.dirty
    assert report.block_reason == "dirty_git_worktree"


def test_collect_changes_and_fingerprint(tmp_path: Path):
    sandbox = ensure_disposable_sandbox(tmp_path / "coding-sandbox")
    (sandbox / "hello.py").write_text(
        'def greet(name: str = "world") -> str:\n    return f"Hi, {name}!"\n',
        encoding="utf-8",
    )
    changes = collect_workspace_changes(str(sandbox))
    assert "hello.py" in changes.changed_files
    assert changes.diff_text
    assert changes.diff_fingerprint


def test_validation_runs_allowlisted_pytest(tmp_path: Path):
    sandbox = ensure_disposable_sandbox(tmp_path / "coding-sandbox")
    report = run_validation(str(sandbox), "python -m pytest")
    assert report.status in {"passed", "failed"}
    assert report.command == "python -m pytest"
    assert report.exit_code is not None


def test_validation_rejects_non_allowlisted(tmp_path: Path):
    sandbox = ensure_disposable_sandbox(tmp_path / "coding-sandbox")
    report = run_validation(str(sandbox), "python -c 'print(1)'")
    assert report.status == "rejected_not_allowlisted"


def test_reset_disposable_sandbox(tmp_path: Path):
    sandbox = ensure_disposable_sandbox(tmp_path / "coding-sandbox")
    (sandbox / "extra.txt").write_text("x\n", encoding="utf-8")
    reset = reset_disposable_sandbox(tmp_path / "coding-sandbox")
    assert reset == sandbox
    assert not (sandbox / "extra.txt").exists()
    assert (sandbox / "hello.py").exists()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=sandbox,
        capture_output=True,
        text=True,
        check=False,
    )
    assert status.returncode == 0
    assert status.stdout.strip() == ""
