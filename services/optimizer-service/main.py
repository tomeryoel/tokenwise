"""optimizer-service (Day 5: real LangGraph Optimization Engine).

The mocked static optimizer is replaced by an explicit, deterministic LangGraph
state graph (see graph.py). /agent/run returns the full Optimization Plan plus
the legacy compatibility fields the n8n workflow + React receipt already expect
(selected_tier, estimated_tokens, estimated_cost, cost_saved, optimization_reason).
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from graph import run_optimizer

SERVICE_NAME = "optimizer-service"

app = FastAPI(title=SERVICE_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AgentRunRequest(BaseModel):
    request_id: str | None = None
    prompt: str = ""
    policy_mode: str = "balanced"
    # Signals forwarded by n8n (guardrails + cache + normalized request).
    guardrail_status: str = "passed"
    guardrail_reason: str = ""
    cache_status: str = "miss"
    cache_confidence: float = 0.0
    contains_sensitive_data: bool = False
    require_local_model: bool = False
    allow_external_model: bool = True
    estimated_tokens: int = 0
    quality_requirement: str = ""
    latency_requirement: str = "normal"
    has_image: bool = False
    image_class: str = ""
    image_complexity: float = 0.0
    max_cost: float | None = None


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/agent/run")
def agent_run(req: AgentRunRequest):
    result = run_optimizer(req.model_dump())

    tier = result.get("selected_tier", "cheap")
    task_type = result.get("task_type", "unknown")
    level = result.get("complexity_level", "medium")
    reasons = result.get("decision_reasons", [])

    # Compatibility summary string for the existing receipt field.
    optimization_reason = (
        f"{task_type}/{level} -> {tier} tier "
        f"[{result.get('policy_mode', 'balanced')}]"
    )

    return {
        # --- rich Optimization Plan ---
        "request_id": result.get("request_id", req.request_id or ""),
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
        # --- graph observability (Day 5.1 conditional graph) ---
        "graph_path": result.get("graph_path", "standard_optimization_path"),
        "branch_reason": result.get("branch_reason", ""),
        "executed_nodes": result.get("executed_nodes", []),
        # --- legacy compatibility fields (do not remove) ---
        "estimated_tokens": result.get("estimated_tokens", 0),
        "estimated_cost": result.get("estimated_optimized_cost", 0.0),
        "cost_saved": result.get("estimated_savings", 0.0),
        "optimization_reason": optimization_reason,
    }
