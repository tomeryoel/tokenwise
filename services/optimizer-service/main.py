"""optimizer-service (LangGraph, providers, usage DB, and Langfuse export).

Responsibilities behind separate endpoints/modules:

1. POST /agent/run  - LangGraph Optimization Plan (graph.py)
2. POST /providers/execute - Layer 4 model provider execution (providers/)
3. POST /usage/log, GET /usage/summary, GET /usage/recent - usage persistence (usage/)
4. GET /observability/* - Day 9 Langfuse status and trace lookup (observability/)

Provider and usage modules are packaged inside optimizer-service as an MVP
decision to preserve the lecturer-required four FastAPI microservices.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from graph import run_optimizer
from observability.exporter import get_trace_exporter
from observability.repository import get_export_counts, get_export_record, record_export_attempt
from observability.schemas import ObservabilityStatusResponse, TraceStatusResponse
from policy import PolicyMode, canonicalize_policy_mode
from providers.executor import execute_provider
from providers.ollama_provider import OllamaProvider
from providers.openai_provider import OpenAIProvider
from providers.schemas import ProviderExecuteRequest
from usage.analytics import get_recent, get_summary
from usage.database import init_db
from usage.repository import log_usage
from usage.schemas import UsageLogRequest, UsageLogResponse, UsageRecentResponse, UsageSummaryResponse

SERVICE_NAME = "optimizer-service"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    exporter = get_trace_exporter()
    try:
        yield
    finally:
        exporter.shutdown()


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AgentRunRequest(BaseModel):
    request_id: str | None = Field(default=None, min_length=1, max_length=200)
    prompt: str = ""
    policy_mode: PolicyMode = "balanced"
    guardrail_status: str = "passed"
    guardrail_reason: str = ""
    cache_status: str = "miss"
    cache_confidence: float = Field(default=0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    contains_sensitive_data: bool = False
    require_local_model: bool = False
    allow_external_model: bool = True
    prefer_low_cost_tier: bool = False
    estimated_tokens: int = Field(default=0, ge=0)
    quality_requirement: str = ""
    latency_requirement: str = "normal"
    has_image: bool = False
    image_class: str = ""
    image_complexity: float = Field(default=0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    max_cost: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)

    @field_validator("policy_mode", mode="before")
    @classmethod
    def canonicalize_mode(cls, value: object) -> str:
        return canonicalize_policy_mode(value)


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/providers/health")
async def providers_health():
    ollama = OllamaProvider()
    openai = OpenAIProvider()
    ollama_health = await ollama.check_health()
    openai_health = await openai.check_health()
    return {"ollama": ollama_health, "openai": openai_health}


@app.post("/agent/run")
def agent_run(req: AgentRunRequest):
    result = run_optimizer(req.model_dump())

    tier = result.get("selected_tier", "cheap")
    task_type = result.get("task_type", "unknown")
    level = result.get("complexity_level", "medium")
    reasons = result.get("decision_reasons", [])

    optimization_reason = (
        f"{task_type}/{level} -> {tier} tier "
        f"[{result.get('policy_mode', 'balanced')}]"
    )

    return {
        "request_id": result.get("request_id", req.request_id or ""),
        "policy_mode": result.get("policy_mode", "balanced"),
        "task_type": task_type,
        "complexity_score": result.get("complexity_score", 0.0),
        "complexity_level": level,
        "selected_tier": tier,
        "compression_recommended": result.get("compression_recommended", False),
        "compression_target_ratio": result.get("compression_target_ratio", 1.0),
        "compression_reason": result.get("compression_reason", ""),
        "compression_risk": result.get("compression_risk", "low"),
        "fallback_tier": result.get("fallback_tier", "balanced"),
        "fallback_reason": result.get("fallback_reason", ""),
        "escalation_conditions": result.get("escalation_conditions", []),
        "estimated_baseline_cost": result.get("estimated_baseline_cost", 0.0),
        "estimated_optimized_cost": result.get("estimated_optimized_cost", 0.0),
        "estimated_savings": result.get("estimated_savings", 0.0),
        "decision_reasons": reasons,
        "optimization_plan": result.get("optimization_plan", {}),
        "graph_path": result.get("graph_path", "standard_optimization_path"),
        "branch_reason": result.get("branch_reason", ""),
        "executed_nodes": result.get("executed_nodes", []),
        "estimated_tokens": result.get("estimated_tokens", 0),
        "estimated_cost": result.get("estimated_optimized_cost", 0.0),
        "cost_saved": result.get("estimated_savings", 0.0),
        "optimization_reason": optimization_reason,
    }


@app.post("/providers/execute")
async def providers_execute(req: ProviderExecuteRequest):
    return await execute_provider(req)


@app.post("/usage/log", response_model=UsageLogResponse)
def usage_log(req: UsageLogRequest):
    usage_result = log_usage(req)
    exporter = get_trace_exporter()

    def response_with_trace(**updates) -> UsageLogResponse:
        data = usage_result.model_dump()
        data.update(updates)
        return UsageLogResponse(**data)

    try:
        existing = get_export_record(req.request_id)
        if existing and existing.exported:
            return response_with_trace(
                tracing_enabled=exporter.config.requested_enabled,
                trace_exported=True,
                trace_id=existing.trace_id,
                trace_url=exporter.config.browser_trace_url(existing.trace_url),
            )

        trace_result = exporter.export_usage(req)
        if trace_result.attempted:
            record_export_attempt(
                req.request_id,
                trace_id=trace_result.trace_id,
                trace_url=trace_result.trace_url,
                exported=trace_result.exported,
                error=trace_result.error,
            )

        return response_with_trace(
            tracing_enabled=trace_result.tracing_enabled,
            trace_exported=trace_result.exported,
            trace_id=trace_result.trace_id,
            trace_url=trace_result.trace_url,
            trace_error=trace_result.error,
        )
    except Exception as exc:
        # Usage persistence is the source of truth; observability is fail-open.
        return response_with_trace(
            tracing_enabled=exporter.config.requested_enabled,
            trace_error=str(exc)[:500],
        )


@app.get("/observability/status", response_model=ObservabilityStatusResponse)
def observability_status():
    exporter = get_trace_exporter()
    counts = get_export_counts()
    config = exporter.config
    return ObservabilityStatusResponse(
        requested_enabled=config.requested_enabled,
        configured=config.configured,
        active=config.active,
        client_ready=exporter.client_ready,
        base_url=config.base_url,
        public_url=config.public_url or config.base_url,
        environment=config.environment,
        release=config.release,
        exported_traces=counts["exported"],
        failed_exports=counts["failed"],
        pending_exports=counts["pending"],
        initialization_error=exporter.initialization_error,
    )


@app.get("/observability/traces/{request_id}", response_model=TraceStatusResponse)
def observability_trace_status(request_id: str):
    record = get_export_record(request_id)
    if record is None:
        return TraceStatusResponse(request_id=request_id, found=False)
    exporter = get_trace_exporter()
    return TraceStatusResponse(
        request_id=request_id,
        found=True,
        exported=record.exported,
        attempt_count=record.attempt_count,
        trace_id=record.trace_id,
        trace_url=exporter.config.browser_trace_url(record.trace_url),
        last_error=record.last_error,
    )


@app.get("/usage/summary", response_model=UsageSummaryResponse)
def usage_summary(
    dept_id: str | None = Query(default=None),
    period_days: int = Query(default=30, ge=1, le=365),
    operating_cost_usd: float | None = Query(default=None, gt=0, allow_inf_nan=False),
):
    return get_summary(
        period_days=period_days,
        dept_id=dept_id,
        operating_cost_usd=operating_cost_usd,
    )


@app.get("/usage/recent", response_model=UsageRecentResponse)
def usage_recent(
    limit: int = Query(default=20, ge=1, le=100),
    dept_id: str | None = Query(default=None),
):
    return get_recent(limit=limit, dept_id=dept_id)
