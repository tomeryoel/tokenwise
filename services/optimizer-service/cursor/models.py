"""Cursor model catalog loading and normalization."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "cursor_models.json"


@dataclass(frozen=True)
class CursorModel:
    id: str
    display_name: str
    family: str
    route_class: str
    momihelm_tier: str
    relative_cost: float
    relative_reasoning: float
    supports_agent: bool
    supports_plan: bool
    aliases: tuple[str, ...]


def _config_path() -> Path:
    override = os.environ.get("CURSOR_MODELS_CONFIG_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return DEFAULT_CONFIG_PATH


def _normalize_key(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[_\s]+", "-", lowered)
    lowered = re.sub(r"[^a-z0-9.\-]+", "", lowered)
    return lowered


@lru_cache(maxsize=1)
def load_cursor_models() -> tuple[CursorModel, ...]:
    path = _config_path()
    payload = json.loads(path.read_text(encoding="utf-8"))
    models: list[CursorModel] = []
    for item in payload.get("models", []):
        models.append(
            CursorModel(
                id=str(item["id"]),
                display_name=str(item["display_name"]),
                family=str(item.get("family", "unknown")),
                route_class=str(item.get("route_class", "balanced")),
                momihelm_tier=str(item.get("momihelm_tier", "balanced")),
                relative_cost=float(item.get("relative_cost", 0.5)),
                relative_reasoning=float(item.get("relative_reasoning", 0.5)),
                supports_agent=bool(item.get("supports_agent", True)),
                supports_plan=bool(item.get("supports_plan", True)),
                aliases=tuple(str(alias) for alias in item.get("aliases", [])),
            )
        )
    return tuple(models)


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for model in load_cursor_models():
        index[_normalize_key(model.id)] = model.id
        index[_normalize_key(model.display_name)] = model.id
        for alias in model.aliases:
            index[_normalize_key(alias)] = model.id
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


def get_cursor_model(model_id: str | None) -> CursorModel | None:
    normalized = normalize_cursor_model_id(model_id)
    if normalized is None:
        return None
    for model in load_cursor_models():
        if model.id == normalized:
            return model
    return None


def list_cursor_models() -> list[dict]:
    return [
        {
            "id": model.id,
            "display_name": model.display_name,
            "family": model.family,
            "route_class": model.route_class,
            "momihelm_tier": model.momihelm_tier,
            "relative_cost": model.relative_cost,
            "relative_reasoning": model.relative_reasoning,
            "supports_agent": model.supports_agent,
            "supports_plan": model.supports_plan,
        }
        for model in load_cursor_models()
    ]
