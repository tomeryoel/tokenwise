"""Deterministic, correctable coding use-case classification."""

from __future__ import annotations

import re
from dataclasses import dataclass


CODING_TASK_TYPES = {
    "bug_investigation",
    "bug_fix",
    "feature_implementation",
    "refactor",
    "test_generation",
    "code_review",
    "architecture_design",
    "documentation",
    "coding_ideation",
    "unknown",
}


@dataclass(frozen=True)
class CodingClassification:
    task_type: str
    confidence: float
    reason: str
    clarification_required: bool = False


def _matches(text: str, *patterns: str) -> str | None:
    for pattern in patterns:
        if re.search(pattern, text):
            return pattern
    return None


def classify_coding_use_case(objective: str) -> CodingClassification:
    """Classify the user objective without claiming learned intelligence."""
    text = re.sub(r"\s+", " ", (objective or "").strip().lower())

    rules = (
        (
            "test_generation",
            0.94,
            False,
            (
                r"\b(write|add|create|generate)\b.{0,24}\b(unit |integration |e2e )?tests?\b",
                r"\b(test coverage|pytest|jest|vitest)\b",
            ),
        ),
        (
            "code_review",
            0.94,
            False,
            (
                r"\b(code|pull request|pr)\s+review\b",
                r"\breview\b.{0,24}\b(code|diff|implementation)\b",
            ),
        ),
        (
            "refactor",
            0.95,
            False,
            (r"\brefactor\b", r"\b(clean up|restructure)\b.{0,24}\bcode\b"),
        ),
        (
            "architecture_design",
            0.90,
            False,
            (
                r"\b(design|compare)\b.{0,30}\b(architecture|system|services?)\b",
                r"\barchitecture\b.{0,30}\b(trade-?offs?|design)\b",
            ),
        ),
        (
            "documentation",
            0.90,
            False,
            (
                r"\b(write|update|create)\b.{0,24}\b(readme|documentation|docs)\b",
                r"\bdocument\b.{0,24}\b(api|code|project)\b",
            ),
        ),
        (
            "bug_fix",
            0.92,
            False,
            (
                r"\b(fix|resolve|patch)\b.{0,30}\b(bug|error|failure|exception|issue)\b",
                r"\b(bug|error|failure|exception)\b.{0,30}\b(fix|resolve|patch)\b",
            ),
        ),
        (
            "bug_investigation",
            0.90,
            False,
            (
                r"\b(investigate|debug|diagnose|find the root cause)\b",
                r"\bwhy\b.{0,30}\b(failing|broken|crashing|error)\b",
                r"\b(stack trace|traceback|memory leak)\b",
            ),
        ),
        (
            "feature_implementation",
            0.88,
            False,
            (
                r"\b(implement|add|build|create)\b.{0,30}\b(feature|function|class|api|app|website|component)\b",
                r"\b(write code|code a|implement this)\b",
            ),
        ),
        (
            "coding_ideation",
            0.84,
            True,
            (
                r"\bcode with me\b",
                r"\b(coding|software)\b.{0,24}\b(idea|project|game)\b",
                r"\b(game|app)\b.{0,24}\bidea\b",
            ),
        ),
    )

    for task_type, confidence, clarification_required, patterns in rules:
        matched = _matches(text, *patterns)
        if matched:
            return CodingClassification(
                task_type=task_type,
                confidence=confidence,
                reason=f"matched deterministic coding pattern: {matched}",
                clarification_required=clarification_required,
            )

    return CodingClassification(
        task_type="unknown",
        confidence=0.20,
        reason="no coding use-case pattern matched",
        clarification_required=True,
    )
