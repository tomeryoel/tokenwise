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
    assert "python3 -m pytest" in VALIDATION_ALLOWLIST
    assert validation_allowed("  npm   test  ")
    assert validation_allowed("python3 -m pytest")
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
    cache_dir = sandbox / "__pycache__"
    cache_dir.mkdir(exist_ok=True)
    (cache_dir / "hello.cpython-314.pyc").write_bytes(b"\0\0")
    (sandbox / ".pytest_cache").mkdir(exist_ok=True)
    (sandbox / ".pytest_cache" / "v").write_text("1\n", encoding="utf-8")

    changes = collect_workspace_changes(str(sandbox))
    assert "hello.py" in changes.changed_files
    assert "__pycache__/" not in changes.changed_files
    assert not any("__pycache__" in item for item in changes.changed_files)
    assert not any(".pytest_cache" in item for item in changes.changed_files)
    assert changes.diff_text
    assert "__pycache__" not in (changes.diff_text or "")
    assert changes.diff_fingerprint

    # Generated cache alone must not hard-block a coding run.
    subprocess.run(["git", "checkout", "--", "hello.py"], cwd=sandbox, check=True)
    report = git_preflight(str(sandbox))
    assert not report.dirty
    assert report.block_reason is None


def test_collect_changes_includes_untracked_file_diff(tmp_path: Path):
    sandbox = ensure_disposable_sandbox(tmp_path / "coding-sandbox")
    (sandbox / "names.py").write_text(
        'def normalize_name(name: str) -> str:\n    return " ".join(name.split())\n',
        encoding="utf-8",
    )

    changes = collect_workspace_changes(str(sandbox))
    assert "names.py" in changes.changed_files
    assert changes.diff_text
    assert "normalize_name" in (changes.diff_text or "")
    assert "names.py" in (changes.diff_text or "")
    assert changes.diff_fingerprint


def test_validation_runs_allowlisted_pytest(tmp_path: Path):
    sandbox = ensure_disposable_sandbox(tmp_path / "coding-sandbox")
    report = run_validation(str(sandbox), "python3 -m pytest")
    assert report.status == "passed"
    assert report.command == "python3 -m pytest"
    assert report.exit_code == 0


def test_validation_rejects_non_allowlisted(tmp_path: Path):
    sandbox = ensure_disposable_sandbox(tmp_path / "coding-sandbox")
    report = run_validation(str(sandbox), "python -c 'print(1)'")
    assert report.status == "rejected_not_allowlisted"


def test_validation_timeout_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    sandbox = ensure_disposable_sandbox(tmp_path / "coding-sandbox")

    def _raise_timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="python3 -m pytest", timeout=180)

    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    report = run_validation(str(sandbox), "python3 -m pytest")
    assert report.status == "timed_out"
    assert report.exit_code is None
    assert "timed_out" in (report.stderr or "")


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
