"""optimizer-service (walking skeleton).

Day 1-2: mock optimization "plan". The response shape matches what the real
LangGraph optimizer will return later, so n8n and the UI will not need changes.
The numbers are lightly derived from prompt length + policy_mode so the skeleton
feels alive, but there is NO real decision logic yet.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

SERVICE_NAME = "optimizer-service"

# Mock per-1k-token prices (USD). Real price table + token counting come later.
PREMIUM_PRICE_PER_1K = 0.03
TIER_PRICE_PER_1K = {"local": 0.0, "cheap": 0.0005, "balanced": 0.003, "premium": 0.03}

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
    guardrail_status: str = "passed"
    cache_status: str = "miss"


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/agent/run")
def agent_run(req: AgentRunRequest):
    # MOCK token estimate: ~4 chars per token, rounded.
    estimated_tokens = max(1, round(len(req.prompt) / 4))

    # MOCK tier choice: policy_mode nudges the tier. No real complexity analysis.
    mode = (req.policy_mode or "balanced").lower()
    if mode == "aggressive":
        tier = "cheap"
    elif mode == "conservative":
        tier = "balanced"
    else:
        tier = "cheap" if estimated_tokens < 200 else "balanced"

    tier_price = TIER_PRICE_PER_1K.get(tier, TIER_PRICE_PER_1K["cheap"])
    estimated_cost = round(estimated_tokens / 1000 * tier_price, 6)
    baseline_cost = round(estimated_tokens / 1000 * PREMIUM_PRICE_PER_1K, 6)
    cost_saved = round(max(0.0, baseline_cost - estimated_cost), 6)

    return {
        "selected_tier": tier,
        "estimated_tokens": estimated_tokens,
        "estimated_cost": estimated_cost,
        "optimization_reason": (
            f"[MOCK] policy_mode={mode}, cache={req.cache_status}, "
            f"guardrail={req.guardrail_status} -> {tier} tier"
        ),
        "cost_saved": cost_saved,
    }
