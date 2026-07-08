"""guardrails-service (walking skeleton).

Day 1-2: mock responses only. Real safety + cost-optimization guardrails
(PII/secrets/injection detection, off-topic/empty blocking) come later.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

SERVICE_NAME = "guardrails-service"

app = FastAPI(title=SERVICE_NAME)

# Allow direct browser calls for manual testing during the skeleton phase.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class InputCheckRequest(BaseModel):
    request_id: str | None = None
    prompt: str = ""
    policy_mode: str = "balanced"


class OutputCheckRequest(BaseModel):
    request_id: str | None = None
    answer: str = ""


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/check/input")
def check_input(req: InputCheckRequest):
    # MOCK: always passes. Real rules (PII/secrets/injection/off-topic) come later.
    return {
        "guardrail_status": "passed",
        "reason": None,
        "contains_sensitive_data": False,
        "require_local_model": False,
        "cost_saved_by_blocking": 0,
    }


@app.post("/check/output")
def check_output(req: OutputCheckRequest):
    # MOCK: always passes.
    return {"guardrail_status": "passed", "redacted_text": None}
