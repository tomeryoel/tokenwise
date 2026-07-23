"""Pydantic schemas for usage logging and analytics."""

from pydantic import BaseModel, Field, field_validator, model_validator

from policy import PolicyMode, canonicalize_policy_mode


class UsageLogRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=200)
    organization_id: str = Field(
        default="legacy-local",
        min_length=1,
        max_length=200,
    )
    user_id: str = Field(
        default="legacy-anonymous",
        min_length=1,
        max_length=200,
    )
    dept_id: str = Field(default="unknown", min_length=1, max_length=200)
    policy_mode: PolicyMode = "balanced"
    prompt: str = ""
    task_type: str | None = None
    complexity_level: str | None = None
    guardrail_status: str = "passed"
    guardrail_reason: str | None = None
    detected_risk_type: str | None = None
    cache_status: str = "miss"
    cache_confidence: float = Field(default=0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    graph_path: str | None = None
    status: str = "completed"
    provider: str | None = None
    model: str | None = None
    requested_tier: str | None = None
    executed_tier: str | None = None
    actual_input_tokens: int = Field(default=0, ge=0)
    actual_output_tokens: int = Field(default=0, ge=0)
    actual_total_tokens: int = Field(default=0, ge=0)
    actual_cost: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    cost_calculation_status: str | None = None
    latency_ms: int = Field(default=0, ge=0)
    used_fallback: bool = False
    fallback_reason: str | None = None
    privacy_enforced: bool = False
    prompt_redaction_applied: bool = False
    actual_execution_attempt_count: int = Field(default=0, ge=0)
    savings_source: str = "unknown"
    savings_reason: str | None = None
    estimated_baseline_cost: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    estimated_optimized_cost: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    estimated_savings: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    actual_cost_saved: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    output_guardrail_status: str = "skipped"
    output_guardrail_issues: list[str] = Field(default_factory=list)

    @field_validator("policy_mode", mode="before")
    @classmethod
    def canonicalize_mode(cls, value: object) -> str:
        return canonicalize_policy_mode(value)

    @model_validator(mode="after")
    def validate_token_total(self) -> "UsageLogRequest":
        component_total = self.actual_input_tokens + self.actual_output_tokens
        if component_total > 0 and self.actual_total_tokens != component_total:
            raise ValueError("actual_total_tokens must equal input plus output tokens")
        return self


class UsageLogResponse(BaseModel):
    logged: bool
    request_id: str
    duplicate: bool = False
    tracing_enabled: bool = False
    trace_exported: bool = False
    trace_id: str | None = None
    trace_url: str | None = None
    trace_error: str | None = None


class UsageSummaryResponse(BaseModel):
    period_days: int
    total_requests: int
    completed_requests: int
    blocked_requests: int
    total_actual_cost: float
    total_actual_api_cost: float
    total_estimated_baseline_cost: float
    total_estimated_optimized_cost: float
    total_savings: float
    total_modeled_cost_avoidance: float
    cost_avoidance_basis: str
    actual_cost_savings_request_count: int
    estimated_savings_request_count: int
    unknown_actual_cost_request_count: int
    savings_percentage: float | None = None
    operating_cost_usd: float | None = None
    roi_percentage: float | None = None
    roi_status: str = "operating_cost_not_modeled"
    roi_basis: str = "not_calculated"
    cache_hit_rate: float
    guardrail_block_rate: float
    premium_usage_rate: float
    premium_requested_rate: float
    fallback_rate: float
    average_latency_ms: float
    total_input_tokens: int
    total_output_tokens: int
    requests_by_source: dict[str, int]
    savings_by_source: dict[str, float]
    requests_by_policy_mode: dict[str, int]
    savings_by_policy_mode: dict[str, float]


class RecentRequestItem(BaseModel):
    request_id: str
    created_at: str
    organization_id: str
    user_id: str
    dept_id: str
    policy_mode: PolicyMode
    task_type: str | None
    status: str
    guardrail_status: str | None
    cache_status: str | None
    provider: str | None
    model: str | None
    requested_tier: str | None
    executed_tier: str | None
    actual_total_tokens: int
    latency_ms: int
    savings_source: str
    savings_amount: float
    savings_basis: str


class UsageRecentResponse(BaseModel):
    items: list[RecentRequestItem]
    count: int
