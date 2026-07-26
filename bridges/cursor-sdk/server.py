"""Local MomiHelm Cursor SDK bridge (dev-only).

Runs on the developer machine. Receives authenticated coding-run tasks from the
MomiHelm gateway, executes them through the official cursor-sdk against a local
workspace, and returns status / changed files / diff / validation.

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
    from cursor_sdk import (
        Agent,
        AgentOptions,
        Cursor,
        CursorAgentError,
        LocalAgentOptions,
        SandboxOptions,
    )
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "cursor-sdk is not installed. Create the bridge venv and install "
        "requirements.txt first."
    ) from exc

from workspace_safety import (
    VALIDATION_ALLOWLIST,
    collect_workspace_changes,
    default_workspace_cwd,
    ensure_disposable_sandbox,
    git_preflight,
    normalize_validation_command,
    run_validation,
    validation_allowed,
)


SERVICE_NAME = "momihelm-cursor-bridge"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

BRIDGE_TOKEN = os.environ.get("MOMIHELM_CURSOR_BRIDGE_TOKEN", "").strip()
CURSOR_API_KEY = os.environ.get("CURSOR_API_KEY", "").strip()
SANDBOX_ENABLED = os.environ.get("MOMIHELM_CURSOR_BRIDGE_SANDBOX", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

CLAIM = (
    "MomiHelm can run Cursor coding-agent tasks through the official Cursor SDK "
    "against a local workspace and display status, changed files, diff, and "
    "validation inside the MomiHelm web application."
)


app = FastAPI(title=SERVICE_NAME, docs_url=None, redoc_url=None)


class RunRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=100_000)
    model: str = Field(min_length=1, max_length=200)
    recommended_model: str | None = Field(default=None, max_length=200)
    cwd: str | None = Field(default=None, max_length=1000)
    request_id: str | None = Field(default=None, max_length=200)
    validation_command: str | None = Field(default=None, max_length=200)
    include_diff_in_response: bool = True


class RunResponse(BaseModel):
    status: Literal[
        "finished",
        "error",
        "cancelled",
        "bridge_error",
        "blocked_dirty_worktree",
        "blocked_validation",
        "blocked_preflight",
    ]
    result_text: str | None = None
    run_id: str | None = None
    agent_id: str | None = None
    model_requested: str
    model_used: str | None = None
    recommended_model: str | None = None
    duration_ms: int | None = None
    error: str | None = None
    experimental: bool = True
    claim: str = CLAIM
    workspace_cwd: str | None = None
    workspace_kind: str | None = None
    sdk_sandbox_enabled: bool | None = None
    changed_files: list[str] = Field(default_factory=list)
    diff_text: str | None = None
    diff_fingerprint: str | None = None
    diff_truncated: bool = False
    validation_command: str | None = None
    validation_status: str | None = None
    validation_exit_code: int | None = None
    validation_stdout: str | None = None
    validation_stderr: str | None = None
    persist_raw_diff: bool = False


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


def _workspace_kind(cwd: str) -> str:
    try:
        sandbox = str(ensure_disposable_sandbox())
    except Exception:
        return "custom"
    return "disposable_sandbox" if os.path.samefile(cwd, sandbox) else "custom"


@app.get("/health")
def health(x_momihelm_bridge_token: str | None = Header(default=None)):
    _require_bridge_auth(x_momihelm_bridge_token)
    try:
        default_cwd = default_workspace_cwd()
    except Exception as exc:
        default_cwd = f"unavailable: {exc}"
    preflight = None
    if isinstance(default_cwd, str) and os.path.isdir(default_cwd):
        report = git_preflight(default_cwd)
        preflight = {
            "is_git_repo": report.is_git_repo,
            "dirty": report.dirty,
            "block_reason": report.block_reason,
        }
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "cursor_api_key_configured": bool(CURSOR_API_KEY),
        "default_cwd": default_cwd,
        "sdk_sandbox_enabled_default": SANDBOX_ENABLED,
        "validation_allowlist": sorted(VALIDATION_ALLOWLIST),
        "git_preflight": preflight,
        "experimental": True,
        "bind": f"{DEFAULT_HOST}:{os.environ.get('MOMIHELM_CURSOR_BRIDGE_PORT', DEFAULT_PORT)}",
        "claim": CLAIM,
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

    try:
        cwd = (payload.cwd or default_workspace_cwd()).strip()
    except Exception as exc:
        return RunResponse(
            status="blocked_preflight",
            model_requested=payload.model,
            recommended_model=payload.recommended_model,
            error=f"workspace_unavailable: {exc}",
        )

    if not os.path.isdir(cwd):
        raise HTTPException(status_code=400, detail="cwd_not_found")

    validation_command = normalize_validation_command(payload.validation_command)
    if validation_command and not validation_allowed(validation_command):
        return RunResponse(
            status="blocked_validation",
            model_requested=payload.model,
            recommended_model=payload.recommended_model,
            workspace_cwd=cwd,
            workspace_kind=_workspace_kind(cwd),
            validation_command=validation_command,
            validation_status="rejected_not_allowlisted",
            error=(
                "validation_command_not_allowlisted: "
                + ", ".join(sorted(VALIDATION_ALLOWLIST))
            ),
        )

    preflight = git_preflight(cwd)
    if preflight.block_reason:
        return RunResponse(
            status="blocked_dirty_worktree"
            if preflight.block_reason == "dirty_git_worktree"
            else "blocked_preflight",
            model_requested=payload.model,
            recommended_model=payload.recommended_model,
            workspace_cwd=cwd,
            workspace_kind=_workspace_kind(cwd),
            changed_files=[
                (line[3:] if len(line) > 3 else line).strip()
                for line in preflight.status_lines
            ],
            error=(
                f"{preflight.block_reason}: refuse coding run on a dirty Git "
                "worktree. Reset or commit the workspace first "
                "(use the disposable sandbox for experiments)."
            ),
            validation_command=validation_command,
        )

    local_options = LocalAgentOptions(
        cwd=cwd,
        sandbox_options=SandboxOptions(enabled=SANDBOX_ENABLED),
    )

    started = time.monotonic()
    try:
        result = Agent.prompt(
            payload.prompt,
            AgentOptions(
                api_key=api_key,
                model=payload.model,
                local=local_options,
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
            workspace_cwd=cwd,
            workspace_kind=_workspace_kind(cwd),
            sdk_sandbox_enabled=SANDBOX_ENABLED,
            validation_command=validation_command,
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
            workspace_cwd=cwd,
            workspace_kind=_workspace_kind(cwd),
            sdk_sandbox_enabled=SANDBOX_ENABLED,
            validation_command=validation_command,
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

    changes = collect_workspace_changes(cwd)
    validation_report = None
    if validation_command and status == "finished":
        validation_report = run_validation(cwd, validation_command)

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
        workspace_cwd=cwd,
        workspace_kind=_workspace_kind(cwd),
        sdk_sandbox_enabled=SANDBOX_ENABLED,
        changed_files=changes.changed_files,
        diff_text=changes.diff_text if payload.include_diff_in_response else None,
        diff_fingerprint=changes.diff_fingerprint,
        diff_truncated=changes.diff_truncated,
        validation_command=validation_command,
        validation_status=validation_report.status if validation_report else None,
        validation_exit_code=validation_report.exit_code if validation_report else None,
        validation_stdout=validation_report.stdout if validation_report else None,
        validation_stderr=validation_report.stderr if validation_report else None,
        persist_raw_diff=False,
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
    # Ensure the disposable sandbox exists before advertising the default cwd.
    try:
        ensure_disposable_sandbox()
    except Exception as exc:
        raise SystemExit(f"Could not prepare disposable sandbox: {exc}") from exc

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
