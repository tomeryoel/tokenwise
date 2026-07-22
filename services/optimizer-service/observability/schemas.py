"""Schemas returned by the TokenWise observability layer."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


@dataclass(frozen=True)
class TraceExportResult:
    tracing_enabled: bool
    attempted: bool = False
    exported: bool = False
    trace_id: str | None = None
    trace_url: str | None = None
    error: str | None = None
    skipped_reason: str | None = None


class ObservabilityStatusResponse(BaseModel):
    requested_enabled: bool
    configured: bool
    active: bool
    client_ready: bool
    base_url: str
    public_url: str
    environment: str
    release: str
    exported_traces: int
    failed_exports: int
    pending_exports: int
    initialization_error: str | None = None


class TraceStatusResponse(BaseModel):
    request_id: str
    found: bool
    exported: bool = False
    attempt_count: int = 0
    trace_id: str | None = None
    trace_url: str | None = None
    last_error: str | None = None
