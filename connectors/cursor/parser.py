"""Parse Cursor composer and bubble records from state.vscdb keys."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from connectors.cursor.models import normalize_cursor_model_id
from connectors.cursor.reader import CursorDatabaseSnapshot, load_json_entry


CursorRole = Literal["user", "assistant", "system", "unknown"]
CursorWorkflow = Literal["direct", "plan", "agent", "debug", "review", "unknown"]


@dataclass(frozen=True)
class CursorBubble:
    composer_id: str
    bubble_id: str
    role: CursorRole
    text: str
    model: str | None = None
    workflow: CursorWorkflow = "unknown"
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    created_at: str | None = None


@dataclass(frozen=True)
class CursorComposer:
    composer_id: str
    title: str | None
    workflow: CursorWorkflow
    workspace_path: str | None
    status: str | None
    bubbles: tuple[CursorBubble, ...] = field(default_factory=tuple)

    @property
    def objective(self) -> str:
        for bubble in self.bubbles:
            if bubble.role == "user" and bubble.text.strip():
                return bubble.text.strip()
        if self.title and self.title.strip():
            return self.title.strip()
        return f"Cursor composer {self.composer_id[:8]}"


def _normalize_workflow(raw: object) -> CursorWorkflow:
    if not isinstance(raw, str):
        return "unknown"
    normalized = raw.strip().lower()
    mapping = {
        "agent": "agent",
        "chat": "direct",
        "direct": "direct",
        "plan": "plan",
        "debug": "debug",
        "review": "review",
        "composer": "agent",
    }
    return mapping.get(normalized, "unknown")


def _normalize_role(raw: object) -> CursorRole:
    if isinstance(raw, int):
        if raw == 1:
            return "user"
        if raw == 2:
            return "assistant"
        return "unknown"
    if isinstance(raw, str):
        lowered = raw.lower()
        if lowered in {"user", "human"}:
            return "user"
        if lowered in {"assistant", "ai", "model"}:
            return "assistant"
        if lowered == "system":
            return "system"
    return "unknown"


def _token_count(payload: dict) -> tuple[int, int]:
    token_count = payload.get("tokenCount")
    if isinstance(token_count, dict):
        input_tokens = int(token_count.get("inputTokens") or token_count.get("input") or 0)
        output_tokens = int(
            token_count.get("outputTokens") or token_count.get("output") or 0
        )
        return max(input_tokens, 0), max(output_tokens, 0)

    usage = payload.get("usage")
    if isinstance(usage, dict):
        return max(int(usage.get("input_tokens") or 0), 0), max(
            int(usage.get("output_tokens") or 0), 0
        )
    return 0, 0


def _bubble_from_payload(
    composer_id: str,
    bubble_id: str,
    payload: dict,
    composer_workflow: CursorWorkflow,
) -> CursorBubble:
    text = payload.get("text") or payload.get("rawText") or payload.get("content") or ""
    if not isinstance(text, str):
        text = str(text)
    input_tokens, output_tokens = _token_count(payload)
    timing = payload.get("timingInfo")
    latency_ms = 0
    if isinstance(timing, dict):
        latency_ms = max(int(timing.get("totalMs") or timing.get("durationMs") or 0), 0)

    model = payload.get("modelType") or payload.get("model") or payload.get("modelName")
    if model is not None:
        model = str(model)
    normalized = normalize_cursor_model_id(model)
    if normalized:
        model = normalized

    workflow = _normalize_workflow(
        payload.get("unifiedMode") or payload.get("mode") or composer_workflow
    )

    created_at = payload.get("createdAt") or payload.get("timestamp")
    if created_at is not None:
        created_at = str(created_at)

    return CursorBubble(
        composer_id=composer_id,
        bubble_id=bubble_id,
        role=_normalize_role(payload.get("type") or payload.get("role")),
        text=text.strip(),
        model=model,
        workflow=workflow,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        created_at=created_at,
    )


def _composer_from_payload(composer_id: str, payload: dict) -> CursorComposer:
    workflow = _normalize_workflow(
        payload.get("unifiedMode")
        or payload.get("mode")
        or payload.get("composerMode")
    )
    title = payload.get("name") or payload.get("title")
    if title is not None:
        title = str(title).strip() or None

    workspace_path = payload.get("workspaceFolder") or payload.get("workspacePath")
    if workspace_path is not None:
        workspace_path = str(workspace_path)

    status = payload.get("status")
    if status is not None:
        status = str(status)

    return CursorComposer(
        composer_id=composer_id,
        title=title,
        workflow=workflow,
        workspace_path=workspace_path,
        status=status,
        bubbles=(),
    )


def discover_composers(snapshot: CursorDatabaseSnapshot) -> list[CursorComposer]:
    composer_ids: set[str] = set()
    composer_meta: dict[str, CursorComposer] = {}

    for key in snapshot.keys_with_prefix("composerData:"):
        composer_id = key.split(":", 1)[1]
        composer_ids.add(composer_id)
        payload = load_json_entry(snapshot.get(key))
        if isinstance(payload, dict):
            composer_meta[composer_id] = _composer_from_payload(composer_id, payload)

    bubble_map: dict[str, list[CursorBubble]] = {composer_id: [] for composer_id in composer_ids}

    for key in snapshot.keys_with_prefix("bubbleId:"):
        parts = key.split(":", 2)
        if len(parts) != 3:
            continue
        _, composer_id, bubble_id = parts
        composer_ids.add(composer_id)
        payload = load_json_entry(snapshot.get(key))
        if not isinstance(payload, dict):
            continue
        composer_workflow = composer_meta.get(composer_id, CursorComposer(
            composer_id=composer_id,
            title=None,
            workflow="unknown",
            workspace_path=None,
            status=None,
        )).workflow
        bubble_map.setdefault(composer_id, []).append(
            _bubble_from_payload(composer_id, bubble_id, payload, composer_workflow)
        )

    composers: list[CursorComposer] = []
    for composer_id in sorted(composer_ids):
        base = composer_meta.get(
            composer_id,
            CursorComposer(
                composer_id=composer_id,
                title=None,
                workflow="unknown",
                workspace_path=None,
                status=None,
            ),
        )
        bubbles = tuple(sorted(bubble_map.get(composer_id, []), key=lambda item: item.bubble_id))
        composers.append(
            CursorComposer(
                composer_id=base.composer_id,
                title=base.title,
                workflow=base.workflow,
                workspace_path=base.workspace_path,
                status=base.status,
                bubbles=bubbles,
            )
        )
    return composers
