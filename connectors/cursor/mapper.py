"""Map Cursor composer records to MomiHelm connector ingest payloads."""

from __future__ import annotations

from connectors.cursor.models import normalize_cursor_model_id
from connectors.cursor.parser import CursorBubble, CursorComposer


def composer_to_ingest_payload(composer: CursorComposer) -> dict:
    assistant_bubbles = [
        bubble for bubble in composer.bubbles if bubble.role == "assistant"
    ]
    return {
        "external_composer_id": composer.composer_id,
        "title": composer.title,
        "objective": composer.objective,
        "workflow": composer.workflow,
        "workspace_path": composer.workspace_path,
        "cursor_status": composer.status,
        "bubbles": [_bubble_to_payload(bubble) for bubble in assistant_bubbles],
    }


def _bubble_to_payload(bubble: CursorBubble) -> dict:
    normalized_model = normalize_cursor_model_id(bubble.model)
    return {
        "external_bubble_id": bubble.bubble_id,
        "model": normalized_model or bubble.model,
        "workflow": bubble.workflow,
        "input_tokens": bubble.input_tokens,
        "output_tokens": bubble.output_tokens,
        "latency_ms": bubble.latency_ms,
        "created_at": bubble.created_at,
    }


def build_ingest_batch(composers: list[CursorComposer], *, limit: int = 20) -> dict:
    eligible = [
        composer
        for composer in composers
        if composer.objective.strip()
        and any(bubble.role == "assistant" for bubble in composer.bubbles)
    ]
    eligible.sort(key=lambda item: item.composer_id, reverse=True)
    selected = eligible[: max(1, min(limit, 100))]
    return {
        "composers": [composer_to_ingest_payload(composer) for composer in selected],
        "discovered_count": len(composers),
        "selected_count": len(selected),
    }
