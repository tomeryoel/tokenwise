from __future__ import annotations

import os
import tempfile

import pytest

from usage.database import init_db
from usage.session_repository import ingest_cursor_composers
from usage.session_schemas import (
    CursorBubbleIngest,
    CursorComposerIngest,
    CursorIngestRequest,
)


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


def test_cursor_ingest_is_idempotent(tmp_db):
    req = CursorIngestRequest(
        organization_id="org-a",
        user_id="user-a",
        dept_id="engineering",
        policy_mode="balanced",
        discovered_count=1,
        selected_count=1,
        composers=[
            CursorComposerIngest(
                external_composer_id="composer-abc",
                objective="Fix a Python function that removes duplicate numbers from a list.",
                workflow="agent",
                workspace_path="/Users/demo/tokenwise",
                bubbles=[
                    CursorBubbleIngest(
                        external_bubble_id="assistant-1",
                        model="claude-sonnet-4",
                        workflow="agent",
                        input_tokens=1200,
                        output_tokens=450,
                        latency_ms=4200,
                    )
                ],
            )
        ],
    )

    first = ingest_cursor_composers(req, db_path=tmp_db)
    second = ingest_cursor_composers(req, db_path=tmp_db)

    assert first.sessions_created == 1
    assert first.attempts_created == 1
    assert second.sessions_created == 0
    assert second.sessions_updated == 1
    assert second.attempts_created == 0
    assert second.attempts_skipped == 1
    assert first.composer_links[0].session_id == second.composer_links[0].session_id
