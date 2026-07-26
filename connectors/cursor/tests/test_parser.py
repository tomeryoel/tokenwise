from __future__ import annotations

import json
from pathlib import Path

from connectors.cursor.mapper import build_ingest_batch
from connectors.cursor.parser import discover_composers
from connectors.cursor.reader import CursorDatabaseSnapshot, CursorKvEntry


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_entries.json"


def _load_fixture_snapshot() -> CursorDatabaseSnapshot:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    snapshot = CursorDatabaseSnapshot(databases=[Path("/tmp/fixture.vscdb")])
    for key, value in payload.items():
        snapshot.entries[key] = CursorKvEntry(
            database_path=Path("/tmp/fixture.vscdb"),
            table="ItemTable",
            key=key,
            value=json.dumps(value),
        )
    return snapshot


def test_discover_composers_from_fixture():
    composers = discover_composers(_load_fixture_snapshot())
    assert len(composers) == 1
    composer = composers[0]
    assert composer.composer_id == "composer-abc"
    assert composer.workflow == "agent"
    assert composer.objective.startswith("Fix a Python function")
    assert len(composer.bubbles) == 2


def test_build_ingest_batch_maps_assistant_turns_only():
    composers = discover_composers(_load_fixture_snapshot())
    batch = build_ingest_batch(composers, limit=5)
    assert batch["selected_count"] == 1
    composer = batch["composers"][0]
    assert composer["external_composer_id"] == "composer-abc"
    assert len(composer["bubbles"]) == 1
    assert composer["bubbles"][0]["model"] == "claude-sonnet-4"
    assert composer["bubbles"][0]["input_tokens"] == 1200
