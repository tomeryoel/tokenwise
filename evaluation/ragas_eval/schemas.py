"""Dataset and result schemas + validation for the MomiHelm Ragas evaluation."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# Allowed dataset categories (A/B/C groups from the eval design).
ALLOWED_CATEGORIES = {
    # A. MomiHelm architecture / behavior grounding
    "tokenwise_architecture",
    # B. General AI tasks
    "general_qa",
    "explanation",
    "summarization",
    "translation",
    "code_explanation",
    "structured_writing",
    "reasoning",
    # C. Behavioral system cases
    "behavioral_guardrail",
    "behavioral_privacy",
    "behavioral_cache",
    "behavioral_fallback",
}

# A case is either an answer-quality case (generate + score answers) or a
# behavioral case (assert system behavior; do NOT force answer-quality metrics).
ANSWER_QUALITY = "answer_quality"
BEHAVIORAL = "behavioral"
ALLOWED_KINDS = {ANSWER_QUALITY, BEHAVIORAL}


class DatasetValidationError(ValueError):
    """Raised when the curated dataset violates the schema."""


@dataclass
class EvalCase:
    case_id: str
    category: str
    kind: str
    user_input: str
    reference: Optional[str] = None
    expected_task_type: Optional[str] = None
    expected_behavior: str = "answer"
    expected_route: list[str] = field(default_factory=list)
    quality_critical: bool = False

    # metric applicability (answer-quality cases)
    run_semantic_similarity: bool = False
    run_response_relevancy: bool = False
    run_factual_correctness: bool = False
    run_custom_rubric: bool = False

    # behavioral expectations (behavioral cases)
    expect_blocked: bool = False
    expect_redaction: bool = False
    expect_local_only: bool = False
    expect_no_external: bool = False
    expect_cache_hit_on_repeat: bool = False

    # smoke-mode membership
    smoke: bool = False

    def is_answer_quality(self) -> bool:
        return self.kind == ANSWER_QUALITY

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _require_str(row: dict, key: str, case_id: str) -> str:
    val = row.get(key)
    if not isinstance(val, str) or not val.strip():
        raise DatasetValidationError(f"case '{case_id}': missing/empty required field '{key}'")
    return val


def parse_case(row: dict[str, Any]) -> EvalCase:
    """Validate and build one EvalCase from a raw dict row."""
    case_id = row.get("case_id")
    if not isinstance(case_id, str) or not case_id.strip():
        raise DatasetValidationError("a case is missing a non-empty 'case_id'")

    category = _require_str(row, "category", case_id)
    if category not in ALLOWED_CATEGORIES:
        raise DatasetValidationError(
            f"case '{case_id}': invalid category '{category}'. "
            f"Allowed: {sorted(ALLOWED_CATEGORIES)}"
        )

    kind = row.get("kind", ANSWER_QUALITY)
    if kind not in ALLOWED_KINDS:
        raise DatasetValidationError(
            f"case '{case_id}': invalid kind '{kind}'. Allowed: {sorted(ALLOWED_KINDS)}"
        )

    _require_str(row, "user_input", case_id)

    # answer-quality cases that request a reference-based metric must have a reference
    ref = row.get("reference")
    needs_ref = bool(
        row.get("run_semantic_similarity")
        or row.get("run_factual_correctness")
    )
    if kind == ANSWER_QUALITY and needs_ref and not (isinstance(ref, str) and ref.strip()):
        raise DatasetValidationError(
            f"case '{case_id}': reference-based metric requested but 'reference' is missing"
        )

    known = {f for f in EvalCase.__dataclass_fields__}
    filtered = {k: v for k, v in row.items() if k in known}
    return EvalCase(**filtered)


def validate_dataset(rows: list[dict[str, Any]]) -> list[EvalCase]:
    """Validate the whole dataset: parse each row and reject duplicate ids."""
    if not isinstance(rows, list) or not rows:
        raise DatasetValidationError("dataset must be a non-empty list of cases")

    cases: list[EvalCase] = []
    seen: set[str] = set()
    for row in rows:
        case = parse_case(row)
        if case.case_id in seen:
            raise DatasetValidationError(f"duplicate case_id: '{case.case_id}'")
        seen.add(case.case_id)
        cases.append(case)
    return cases


# --------------------------------------------------------------------------- #
# Result schemas
# --------------------------------------------------------------------------- #
@dataclass
class MetricScore:
    metric: str
    variant: str  # "baseline" | "tokenwise"
    value: Optional[float] = None
    reason: Optional[str] = None
    status: str = "ok"  # ok | error | not_applicable | skipped
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VariantExecution:
    variant: str
    provider: Optional[str] = None
    model: Optional[str] = None
    answer: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    latency_ms: Optional[float] = None
    actual_cost: Optional[float] = None
    modeled_baseline_cost: Optional[float] = None
    modeled_optimized_cost: Optional[float] = None
    receipt: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
