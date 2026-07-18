"""Dataset loading, validation, fingerprinting and smoke/full filtering."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .schemas import EvalCase, DatasetValidationError, validate_dataset

DATASET_PATH = Path(__file__).resolve().parent.parent / "datasets" / "tokenwise_eval_dataset.json"


def load_raw(path: Path | str | None = None) -> dict[str, Any]:
    p = Path(path) if path else DATASET_PATH
    if not p.exists():
        raise DatasetValidationError(f"dataset file not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or "cases" not in data:
        raise DatasetValidationError("dataset must be an object with a 'cases' array")
    return data


def load_cases(path: Path | str | None = None) -> tuple[list[EvalCase], dict[str, Any]]:
    """Return (validated cases, metadata) where metadata has version + fingerprint."""
    data = load_raw(path)
    cases = validate_dataset(data["cases"])
    meta = {
        "dataset_version": data.get("dataset_version", "unknown"),
        "description": data.get("description", ""),
        "case_count": len(cases),
        "fingerprint": fingerprint(data["cases"]),
    }
    return cases, meta


def fingerprint(rows: list[dict[str, Any]]) -> str:
    """Stable SHA-256 fingerprint of the dataset content."""
    canonical = json.dumps(rows, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def filter_for_mode(cases: list[EvalCase], mode: str) -> list[EvalCase]:
    """smoke -> only cases flagged smoke; full -> all cases."""
    if mode == "smoke":
        selected = [c for c in cases if c.smoke]
        if not selected:  # safety net: never run an empty smoke experiment
            selected = cases[:3]
        return selected
    return list(cases)


def filter_by_case_id(cases: list[EvalCase], case_id: str) -> list[EvalCase]:
    """Select exactly one case by id; raise if unknown."""
    wanted = (case_id or "").strip()
    if not wanted:
        raise DatasetValidationError("case_id must be a non-empty string")
    selected = [c for c in cases if c.case_id == wanted]
    if not selected:
        known = ", ".join(c.case_id for c in cases)
        raise DatasetValidationError(
            f"unknown case_id '{wanted}'. Known ids: {known}"
        )
    return selected
