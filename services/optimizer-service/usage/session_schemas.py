"""Typed contracts for coding sessions, attempts, context, and verification."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from policy import PolicyMode, canonicalize_policy_mode
from usage.coding_classifier import CODING_TASK_TYPES


CodingTaskType = Literal[
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
]
CodingSessionStatus = Literal[
    "active",
    "succeeded",
    "partially_succeeded",
    "failed",
    "abandoned",
    "unverified",
]
WorkflowType = Literal["direct", "plan", "agent", "debug", "review", "unknown"]
VerificationType = Literal[
    "tests",
    "build",
    "lint",
    "type_check",
    "static_analysis",
    "user_acceptance",
    "reviewer_assessment",
    "offline_evaluator",
    "connector_completion",
    "rollback",
]
VerificationSource = Literal["user", "automated", "connector", "evaluator"]
VerificationStatus = Literal["passed", "failed", "partial", "skipped"]


def _trim(value: str) -> str:
    return " ".join(value.split())


class CodingSessionCreateRequest(BaseModel):
    organization_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    dept_id: str = Field(min_length=1, max_length=200)
    policy_mode: PolicyMode = "balanced"
    objective: str = Field(min_length=1, max_length=100_000)
    complexity_level: Literal["low", "medium", "high"] | None = None

    @field_validator("organization_id", "user_id", "dept_id", "objective")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return _trim(value)

    @field_validator("policy_mode", mode="before")
    @classmethod
    def normalize_policy(cls, value: object) -> str:
        return canonicalize_policy_mode(value)


class CodingSessionUpdateRequest(BaseModel):
    confirmed_task_type: CodingTaskType | None = None
    status: CodingSessionStatus | None = None

    @model_validator(mode="after")
    def require_change(self) -> "CodingSessionUpdateRequest":
        if self.confirmed_task_type is None and self.status is None:
            raise ValueError("at least one session change is required")
        return self


class ContextSnapshotInput(BaseModel):
    primary_language: str | None = Field(default=None, max_length=80)
    repository_size: Literal["small", "medium", "large", "unknown"] = "unknown"
    files_supplied: int = Field(default=0, ge=0, le=10_000)
    test_files_supplied: int = Field(default=0, ge=0, le=10_000)
    has_error_details: bool = False
    has_acceptance_criteria: bool = False
    has_relevant_tests: bool = False
    approximate_context_tokens: int = Field(default=0, ge=0)
    context_source: Literal["manual", "playground_attachment", "connector"] = "manual"
    privacy_classification: Literal["standard", "sensitive", "restricted"] = "standard"

    @field_validator("primary_language")
    @classmethod
    def normalize_language(cls, value: str | None) -> str | None:
        return _trim(value).lower() if value else None


class CodingAttemptCreateRequest(BaseModel):
    organization_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    request_id: str | None = Field(default=None, min_length=1, max_length=200)
    recommended_tier: str | None = Field(default=None, max_length=40)
    requested_tier: str | None = Field(default=None, max_length=40)
    executed_tier: str | None = Field(default=None, max_length=40)
    provider: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=200)
    recommended_workflow: WorkflowType = "unknown"
    executed_workflow: WorkflowType = "unknown"
    actual_api_cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    modeled_local_cost: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    latency_ms: int = Field(default=0, ge=0)
    context: ContextSnapshotInput | None = None

    @field_validator(
        "organization_id",
        "user_id",
        "request_id",
        "recommended_tier",
        "requested_tier",
        "executed_tier",
        "provider",
        "model",
    )
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        return _trim(value) if value else None


class VerificationCreateRequest(BaseModel):
    organization_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(min_length=1, max_length=200)
    attempt_id: str | None = Field(default=None, min_length=1, max_length=200)
    verification_type: VerificationType
    source: VerificationSource
    status: VerificationStatus
    score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    details: str | None = Field(default=None, max_length=500)

    @field_validator("organization_id", "user_id", "attempt_id", "details")
    @classmethod
    def trim_verification_text(cls, value: str | None) -> str | None:
        return _trim(value) if value else None


class ContextSnapshotResponse(ContextSnapshotInput):
    context_id: str
    attempt_id: str
    created_at: str


class CodingAttemptResponse(BaseModel):
    attempt_id: str
    session_id: str
    attempt_number: int
    request_id: str | None = None
    created_at: str
    completed_at: str | None = None
    recommended_tier: str | None = None
    requested_tier: str | None = None
    executed_tier: str | None = None
    provider: str | None = None
    model: str | None = None
    recommended_workflow: WorkflowType
    executed_workflow: WorkflowType
    actual_api_cost: float | None = None
    modeled_local_cost: float | None = None
    latency_ms: int
    context: ContextSnapshotResponse | None = None


class VerificationResponse(BaseModel):
    verification_id: str
    session_id: str
    attempt_id: str | None = None
    verification_type: VerificationType
    source: VerificationSource
    status: VerificationStatus
    score: float | None = None
    details: str | None = None
    created_at: str


class CodingSessionSummary(BaseModel):
    session_id: str
    organization_id: str
    user_id: str
    dept_id: str
    policy_mode: PolicyMode
    objective_fingerprint: str
    predicted_task_type: CodingTaskType
    confirmed_task_type: CodingTaskType | None = None
    classification_confidence: float
    classification_source: str
    classification_reason: str
    clarification_required: bool
    complexity_level: Literal["low", "medium", "high"] | None = None
    status: CodingSessionStatus
    created_at: str
    updated_at: str
    completed_at: str | None = None

    @field_validator("predicted_task_type", "confirmed_task_type")
    @classmethod
    def validate_task_type(cls, value: str | None) -> str | None:
        if value is not None and value not in CODING_TASK_TYPES:
            raise ValueError("unsupported coding task type")
        return value


class CodingSessionDetail(CodingSessionSummary):
    attempts: list[CodingAttemptResponse] = Field(default_factory=list)
    verification_events: list[VerificationResponse] = Field(default_factory=list)


class CodingSessionListResponse(BaseModel):
    items: list[CodingSessionSummary]
    count: int
