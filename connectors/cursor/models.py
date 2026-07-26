"""Shared Cursor model catalog access for the host-side connector."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path


CONFIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "optimizer-service"
    / "config"
    / "cursor_models.json"
)


def _normalize_key(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[_\s]+", "-", lowered)
    lowered = re.sub(r"[^a-z0-9.\-]+", "", lowered)
    return lowered


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, str]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    index: dict[str, str] = {}
    for item in payload.get("models", []):
        model_id = str(item["id"])
        index[_normalize_key(model_id)] = model_id
        index[_normalize_key(str(item["display_name"]))] = model_id
        for alias in item.get("aliases", []):
            index[_normalize_key(str(alias))] = model_id
    return index


def normalize_cursor_model_id(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    if cleaned.lower() == "auto":
        return "auto"
    return _alias_index().get(_normalize_key(cleaned))
