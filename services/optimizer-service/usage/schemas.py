"""Pydantic schemas for usage logging and analytics."""

from pydantic import BaseModel, Field


class UsageLogRequest(BaseModel):
    request_id: str
    dept_id: str = "unknown"
    policy_mode: str = "balanced"
    prompt: str = ""
    task_type: str | None = None
    complexity_level: str | None = None
    guardrail_status: str = "passed"
    guardrail_reason: str | None = None
    detected_risk_type: str | None = None
    cache_status: str = "miss"
    cache_confidence: float = 0.0
    graph_path: str | None = None
    status: str = "completed"
    provider: str | None = None
    model: str | None = None
    requested_tier: str | None = None
    executed_tier: str | None = None
    actual_input_tokens: int = 0
    actual_output_tokens: int = 0
    actual_total_tokens: int = 0
    actual_cost: float | None = None
    cost_calculation_status: str | None = None
    latency_ms: int = 0
    used_fallback: bool = False
    fallback_reason: str | None = None
    privacy_enforced: bool = False
    prompt_redaction_applied: bool = False
    actual_execution_attempt_count: int = 0
    savings_source: str = "unknown"
    savings_reason: str | None = None
    estimated_baseline_cost: float = 0.0
    estimated_optimized_cost: float = 0.0
    estimated_savings: float = 0.0
    actual_cost_saved: float | None = None
    output_guardrail_status: str = "skipped"
    output_guardrail_issues: list[str] = Field(default_factory=list)


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
    total_estimated_baseline_cost: float
    total_savings: float
    savings_percentage: float | None = None
    roi_percentage: float | None = None
    roi_status: str = "operating_cost_not_modeled"
    cache_hit_rate: float
    guardrail_block_rate: float
    premium_usage_rate: float
    fallback_rate: float
    average_latency_ms: float
    total_input_tokens: int
    total_output_tokens: int
    requests_by_source: dict[str, int]
    savings_by_source: dict[str, float]


class RecentRequestItem(BaseModel):
    request_id: str
    created_at: str
    dept_id: str
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


class UsageRecentResponse(BaseModel):
    items: list[RecentRequestItem]
    count: int
