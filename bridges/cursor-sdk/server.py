"""Local MomiHelm Cursor SDK bridge (dev-only).

Runs on the developer machine. Receives authenticated tasks from the MomiHelm
gateway, executes them through the official cursor-sdk, and returns results.

Does not read or write Cursor state.vscdb.
Does not control the Cursor IDE chat UI.
"""

from __future__ import annotations

import os
import secrets
import time
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

try:
    from cursor_sdk import Agent, AgentOptions, Cursor, CursorAgentError, LocalAgentOptions
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "cursor-sdk is not installed. Create the bridge venv and install "
        "requirements.txt first."
    ) from exc


SERVICE_NAME = "momihelm-cursor-bridge"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

BRIDGE_TOKEN = os.environ.get("MOMIHELM_CURSOR_BRIDGE_TOKEN", "").strip()
CURSOR_API_KEY = os.environ.get("CURSOR_API_KEY", "").strip()
DEFAULT_CWD = os.environ.get(
    "MOMIHELM_CURSOR_BRIDGE_CWD",
    os.environ.get("PWD", os.getcwd()),
).strip()


app = FastAPI(title=SERVICE_NAME, docs_url=None, redoc_url=None)


class RunRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=100_000)
    model: str = Field(min_length=1, max_length=200)
    recommended_model: str | None = Field(default=None, max_length=200)
    cwd: str | None = Field(default=None, max_length=1000)
    request_id: str | None = Field(default=None, max_length=200)


class RunResponse(BaseModel):
    status: Literal["finished", "error", "cancelled", "bridge_error"]
    result_text: str | None = None
    run_id: str | None = None
    agent_id: str | None = None
    model_requested: str
    model_used: str | None = None
    recommended_model: str | None = None
    duration_ms: int | None = None
    error: str | None = None
    experimental: bool = True
    claim: str = (
        "MomiHelm can run Cursor Agent tasks through the official Cursor SDK "
        "and display the result inside the MomiHelm web application."
    )


def _require_bridge_auth(token: str | None) -> None:
    if not BRIDGE_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="bridge_token_not_configured",
        )
    provided = (token or "").strip()
    if not provided or not secrets.compare_digest(provided, BRIDGE_TOKEN):
        raise HTTPException(status_code=401, detail="bridge_authentication_required")


def _require_api_key() -> str:
    if not CURSOR_API_KEY:
        raise HTTPException(status_code=503, detail="cursor_api_key_missing")
    return CURSOR_API_KEY


def _model_to_dict(model: Any) -> dict[str, Any]:
    model_id = getattr(model, "id", None) or getattr(model, "model_id", None)
    if model_id is None and isinstance(model, dict):
        model_id = model.get("id") or model.get("model_id")
    display = getattr(model, "display_name", None) or getattr(model, "name", None)
    if display is None and isinstance(model, dict):
        display = model.get("display_name") or model.get("name")
    return {
        "id": str(model_id) if model_id is not None else "unknown",
        "display_name": str(display or model_id or "unknown"),
    }


@app.get("/health")
def health(x_momihelm_bridge_token: str | None = Header(default=None)):
    _require_bridge_auth(x_momihelm_bridge_token)
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "cursor_api_key_configured": bool(CURSOR_API_KEY),
        "default_cwd": DEFAULT_CWD,
        "experimental": True,
        "bind": f"{DEFAULT_HOST}:{os.environ.get('MOMIHELM_CURSOR_BRIDGE_PORT', DEFAULT_PORT)}",
    }


@app.get("/models")
def list_models(x_momihelm_bridge_token: str | None = Header(default=None)):
    _require_bridge_auth(x_momihelm_bridge_token)
    api_key = _require_api_key()
    try:
        models = Cursor.models.list(api_key=api_key)
    except Exception as exc:  # pragma: no cover - network/auth dependent
        raise HTTPException(
            status_code=502,
            detail=f"cursor_models_unavailable: {exc}",
        ) from exc
    items = [_model_to_dict(model) for model in models]
    return {"models": items, "count": len(items), "source": "cursor_sdk"}


@app.post("/run", response_model=RunResponse)
def run_agent(
    payload: RunRequest,
    x_momihelm_bridge_token: str | None = Header(default=None),
):
    _require_bridge_auth(x_momihelm_bridge_token)
    api_key = _require_api_key()
    cwd = (payload.cwd or DEFAULT_CWD).strip() or DEFAULT_CWD
    if not os.path.isdir(cwd):
        raise HTTPException(status_code=400, detail="cwd_not_found")

    started = time.monotonic()
    try:
        result = Agent.prompt(
            payload.prompt,
            AgentOptions(
                api_key=api_key,
                model=payload.model,
                local=LocalAgentOptions(cwd=cwd),
            ),
        )
    except CursorAgentError as exc:
        return RunResponse(
            status="bridge_error",
            result_text=None,
            run_id=None,
            agent_id=None,
            model_requested=payload.model,
            model_used=None,
            recommended_model=payload.recommended_model,
            duration_ms=int((time.monotonic() - started) * 1000),
            error=f"cursor_agent_startup_failed: {exc}",
        )
    except Exception as exc:  # pragma: no cover
        return RunResponse(
            status="bridge_error",
            result_text=None,
            run_id=None,
            agent_id=None,
            model_requested=payload.model,
            model_used=None,
            recommended_model=payload.recommended_model,
            duration_ms=int((time.monotonic() - started) * 1000),
            error=f"cursor_sdk_error: {exc}",
        )

    model_used = None
    model_obj = getattr(result, "model", None)
    if model_obj is not None:
        model_used = getattr(model_obj, "id", None) or str(model_obj)

    status_raw = str(getattr(result, "status", "error"))
    if status_raw in {"finished", "error", "cancelled"}:
        status = status_raw  # type: ignore[assignment]
    else:
        status = "error"

    return RunResponse(
        status=status,
        result_text=getattr(result, "result", None),
        run_id=getattr(result, "id", None),
        agent_id=getattr(result, "agent_id", None),
        model_requested=payload.model,
        model_used=model_used,
        recommended_model=payload.recommended_model,
        duration_ms=getattr(result, "duration_ms", None)
        or int((time.monotonic() - started) * 1000),
        error=None if status == "finished" else f"run_status_{status}",
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def main() -> None:
    import uvicorn

    if not BRIDGE_TOKEN:
        raise SystemExit(
            "Set MOMIHELM_CURSOR_BRIDGE_TOKEN before starting the bridge."
        )
    host = os.environ.get("MOMIHELM_CURSOR_BRIDGE_HOST", DEFAULT_HOST)
    port = int(os.environ.get("MOMIHELM_CURSOR_BRIDGE_PORT", str(DEFAULT_PORT)))
    uvicorn.run(
        "server:app",
        host=host,
        port=port,
        log_level="info",
        factory=False,
    )


if __name__ == "__main__":
    main()
