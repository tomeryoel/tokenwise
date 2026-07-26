from __future__ import annotations

import os
import tempfile

import pytest

from usage.database import init_db
from usage.session_repository import persist_cursor_sdk_run
from usage.session_schemas import CursorSdkRunPersistRequest


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


def test_persist_cursor_sdk_run_fingerprints_result(tmp_db):
    req = CursorSdkRunPersistRequest(
        organization_id="org-a",
        user_id="user-a",
        dept_id="engineering",
        policy_mode="balanced",
        objective="Add a health check endpoint to the gateway service.",
        selected_model="composer-2.5",
        recommended_model="composer-2.5",
        model_used="composer-2.5",
        sdk_run_id="run-123",
        sdk_agent_id="agent-123",
        status="finished",
        result_text="Added /health and a unit test.",
        duration_ms=1200,
        workflow="agent",
        workspace_kind="disposable_sandbox",
        changed_files=["hello.py"],
        diff_fingerprint="abc123",
        validation_command="python -m pytest",
        validation_status="passed",
    )
    first = persist_cursor_sdk_run(req, db_path=tmp_db)
    second = persist_cursor_sdk_run(req, db_path=tmp_db)

    assert first.provider == "cursor-sdk"
    assert first.result_fingerprint
    assert first.attempt_id
    assert first.session_id
    assert first.changed_files == ["hello.py"]
    assert first.diff_fingerprint == "abc123"
    assert first.validation_status == "passed"
    assert second.attempt_id == first.attempt_id
    assert second.run_key == first.run_key
