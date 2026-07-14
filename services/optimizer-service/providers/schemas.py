"""Pydantic schemas for provider execution (Layer 4)."""

from pydantic import BaseModel, Field


class OptimizationPlanInput(BaseModel):
    route: str = "cheap"
    compress: bool = False
    compression_target_ratio: float = 1.0
    local_only: bool = False
    allow_external: bool = True
    fallback_tier: str = "balanced"


class ProviderExecuteRequest(BaseModel):
    request_id: str = ""
    prompt: str = ""
    selected_tier: str = "cheap"
    fallback_tier: str = "balanced"
    policy_mode: str = "balanced"
    contains_sensitive_data: bool = False
    require_local_model: bool = False
    allow_external_model: bool = True
    prompt_redaction_applied: bool = False
    estimated_tokens: int = 0
    estimated_baseline_cost: float = 0.0
    estimated_optimized_cost: float = 0.0
    optimization_plan: OptimizationPlanInput = Field(default_factory=OptimizationPlanInput)


class ProviderAttempt(BaseModel):
    provider: str
    tier: str
    model: str = ""
    executed: bool = False
    success: bool
    error_code: str | None = None
    error_message: str | None = None
    attempt_role: str = "primary"  # primary | fallback | configuration_check


class ProviderExecuteResponse(BaseModel):
    success: bool
    answer: str | None = None
    provider: str | None = None
    model: str | None = None
    requested_tier: str = ""
    executed_tier: str = ""
    actual_input_tokens: int = 0
    actual_output_tokens: int = 0
    actual_total_tokens: int = 0
    actual_cost: float | None = None
    actual_cost_saved: float | None = None
    latency_ms: int = 0
    provider_total_duration_ms: int | None = None
    provider_load_duration_ms: int | None = None
    used_fallback: bool = False
    fallback_reason: str | None = None
    privacy_enforced: bool = False
    privacy_reason: str | None = None
    prompt_redaction_applied: bool = False
    cost_calculation_status: str = "not_applicable"
    attempts: list[ProviderAttempt] = Field(default_factory=list)
    actual_execution_attempt_count: int = 0
    error_code: str | None = None
    error_message: str | None = None
