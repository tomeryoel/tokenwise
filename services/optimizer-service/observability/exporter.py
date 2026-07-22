"""Build one privacy-safe Langfuse trace from each terminal usage record."""

from __future__ import annotations

import hashlib
import logging
from functools import lru_cache
from typing import Any

from observability.config import ObservabilityConfig
from observability.schemas import TraceExportResult
from usage.repository import prompt_fingerprint
from usage.schemas import UsageLogRequest

logger = logging.getLogger(__name__)


def _savings_amount(req: UsageLogRequest) -> float:
    if req.actual_cost_saved is not None:
        return max(0.0, req.actual_cost_saved)
    return max(0.0, req.estimated_savings)


def _prompt_redaction_applied(req: UsageLogRequest) -> bool:
    return (
        req.prompt_redaction_applied
        or req.privacy_enforced
        or req.guardrail_status == "passed_with_redaction"
    )


def _provider_called(req: UsageLogRequest) -> bool:
    return req.actual_execution_attempt_count > 0 or req.actual_total_tokens > 0


class LangfuseTraceExporter:
    def __init__(
        self,
        config: ObservabilityConfig | None = None,
        client: Any | None = None,
    ) -> None:
        self.config = config or ObservabilityConfig.from_env()
        self._client = client
        self.initialization_error: str | None = None

        if self.config.active and self._client is None:
            try:
                from langfuse import Langfuse

                self._client = Langfuse(
                    public_key=self.config.public_key,
                    secret_key=self.config.secret_key,
                    base_url=self.config.base_url,
                    environment=self.config.environment,
                    release=self.config.release,
                    tracing_enabled=True,
                )
            except Exception as exc:  # pragma: no cover - environment-specific
                self.initialization_error = str(exc)[:500]
                logger.exception("Langfuse client initialization failed")

    @property
    def client_ready(self) -> bool:
        return self.config.active and self._client is not None

    def export_usage(self, req: UsageLogRequest) -> TraceExportResult:
        if not self.config.requested_enabled:
            return TraceExportResult(
                tracing_enabled=False,
                skipped_reason="tracing_disabled",
            )
        if not self.config.configured:
            return TraceExportResult(
                tracing_enabled=True,
                error="Langfuse credentials or base URL are not configured",
                skipped_reason="configuration_incomplete",
            )
        if self._client is None:
            return TraceExportResult(
                tracing_enabled=True,
                error=self.initialization_error or "Langfuse client is unavailable",
                skipped_reason="client_unavailable",
            )

        trace_id: str | None = None
        try:
            trace_id = self._client.create_trace_id(seed=req.request_id)
            parent_span_id = hashlib.sha256(
                f"tokenwise:{req.request_id}:root".encode("utf-8")
            ).hexdigest()[:16]
            fingerprint = prompt_fingerprint(req.prompt)
            stages: list[str] = []

            root_metadata = {
                "request_id": req.request_id,
                "dept_id": req.dept_id,
                "policy_mode": req.policy_mode,
                "task_type": req.task_type or "unknown",
                "status": req.status,
                "graph_path": req.graph_path or "not_run",
                "requested_tier": req.requested_tier or "none",
                "executed_tier": req.executed_tier or "none",
                "savings_source": req.savings_source,
                "savings_reason": req.savings_reason or "unknown",
                "estimated_baseline_cost": req.estimated_baseline_cost,
                "estimated_optimized_cost": req.estimated_optimized_cost,
                "actual_cost": req.actual_cost,
                "cost_saved": _savings_amount(req),
                "privacy_enforced": req.privacy_enforced,
                "prompt_redaction_applied": _prompt_redaction_applied(req),
                "raw_prompt_exported": False,
                "raw_answer_exported": False,
            }
            root_input = {
                "request_id": req.request_id,
                "prompt_fingerprint": fingerprint,
                "prompt_content_logged": False,
            }

            with self._client.start_as_current_observation(
                name="tokenwise_request",
                as_type="chain",
                trace_context={
                    "trace_id": trace_id,
                    "parent_span_id": parent_span_id,
                },
                input=root_input,
                metadata=root_metadata,
            ) as root:
                self._add_guardrail_span(root, req, stages)
                self._add_cache_lookup_span(root, req, stages)
                self._add_image_span(root, req, stages)
                self._add_optimizer_span(root, req, stages)
                self._add_provider_span(root, req, fingerprint, stages)
                self._add_output_guardrail_span(root, req, stages)
                self._add_cache_store_span(root, req, stages)
                self._add_usage_log_span(root, req, stages)
                root.update(
                    output={
                        "status": req.status,
                        "stages": stages,
                        "savings_source": req.savings_source,
                        "cost_saved": _savings_amount(req),
                    }
                )

            if self.config.flush_on_export:
                self._client.flush()
            trace_url = self.config.browser_trace_url(
                self._client.get_trace_url(trace_id=trace_id)
            )
            return TraceExportResult(
                tracing_enabled=True,
                attempted=True,
                exported=True,
                trace_id=trace_id,
                trace_url=trace_url,
            )
        except Exception as exc:  # observability must never break request handling
            error = str(exc)[:500]
            logger.exception("Langfuse export failed for request_id=%s", req.request_id)
            return TraceExportResult(
                tracing_enabled=True,
                attempted=True,
                exported=False,
                trace_id=trace_id,
                error=error,
            )

    @staticmethod
    def _add_guardrail_span(root: Any, req: UsageLogRequest, stages: list[str]) -> None:
        stages.append("input_guardrail")
        level = "WARNING" if req.guardrail_status == "blocked" else "DEFAULT"
        with root.start_as_current_observation(
            name="input_guardrail",
            as_type="guardrail",
            metadata={
                "risk_type": req.detected_risk_type or "none",
                "privacy_enforced": req.privacy_enforced,
                "prompt_redaction_applied": _prompt_redaction_applied(req),
            },
            level=level,
        ) as span:
            span.update(
                output={
                    "status": req.guardrail_status,
                    "reason": req.guardrail_reason or "none",
                }
            )

    @staticmethod
    def _add_cache_lookup_span(root: Any, req: UsageLogRequest, stages: list[str]) -> None:
        if req.cache_status not in {"hit", "miss"}:
            return
        stages.append("semantic_cache_lookup")
        with root.start_as_current_observation(
            name="semantic_cache_lookup",
            as_type="retriever",
            metadata={"dept_id": req.dept_id},
        ) as span:
            span.update(
                output={
                    "status": req.cache_status,
                    "confidence": req.cache_confidence,
                }
            )

    @staticmethod
    def _add_image_span(root: Any, req: UsageLogRequest, stages: list[str]) -> None:
        is_image_path = (
            req.graph_path == "vision_path"
            or req.savings_source == "image_analysis"
            or req.executed_tier == "vision"
        )
        if not is_image_path:
            return
        stages.append("image_analysis")
        with root.start_as_current_observation(
            name="image_analysis",
            as_type="tool",
            metadata={"provider": req.provider or "image-analyser-service"},
        ) as span:
            span.update(
                output={
                    "selected_tier": req.executed_tier or "vision",
                    "graph_path": req.graph_path or "vision_path",
                }
            )

    @staticmethod
    def _add_optimizer_span(root: Any, req: UsageLogRequest, stages: list[str]) -> None:
        if not req.graph_path or req.graph_path in {"reject_path", "cache_path"}:
            return
        stages.append("optimizer")
        with root.start_as_current_observation(
            name="optimizer",
            as_type="chain",
            metadata={"policy_mode": req.policy_mode},
        ) as span:
            span.update(
                output={
                    "graph_path": req.graph_path,
                    "requested_tier": req.requested_tier,
                    "routing_reason": req.savings_reason,
                    "estimated_baseline_cost": req.estimated_baseline_cost,
                    "estimated_optimized_cost": req.estimated_optimized_cost,
                }
            )

    @staticmethod
    def _add_provider_span(
        root: Any,
        req: UsageLogRequest,
        fingerprint: str,
        stages: list[str],
    ) -> None:
        if not _provider_called(req):
            return
        stages.append("provider_execution")
        is_error = req.status == "provider_failed"
        with root.start_as_current_observation(
            name="provider_execution",
            as_type="generation",
            model=req.model or "unknown",
            input={
                "request_id": req.request_id,
                "prompt_fingerprint": fingerprint,
                "prompt_content_logged": False,
            },
            metadata={
                "provider": req.provider or "unknown",
                "requested_tier": req.requested_tier or "none",
                "executed_tier": req.executed_tier or "none",
                "latency_ms": req.latency_ms,
                "used_fallback": req.used_fallback,
                "fallback_reason": req.fallback_reason or "none",
                "privacy_enforced": req.privacy_enforced,
                "execution_attempt_count": req.actual_execution_attempt_count,
                "cost_calculation_status": req.cost_calculation_status or "unknown",
            },
            level="ERROR" if is_error else "DEFAULT",
        ) as generation:
            usage_details = {
                "input": max(0, req.actual_input_tokens),
                "output": max(0, req.actual_output_tokens),
                "total": max(0, req.actual_total_tokens),
            }
            update: dict[str, Any] = {
                "output": {
                    "success": not is_error,
                    "answer_content_logged": False,
                },
                "usage_details": usage_details,
            }
            if req.actual_cost is not None:
                update["cost_details"] = {"total": max(0.0, req.actual_cost)}
            generation.update(**update)

    @staticmethod
    def _add_output_guardrail_span(root: Any, req: UsageLogRequest, stages: list[str]) -> None:
        if req.output_guardrail_status == "skipped":
            return
        stages.append("output_guardrail")
        level = "WARNING" if req.output_guardrail_status == "blocked" else "DEFAULT"
        with root.start_as_current_observation(
            name="output_guardrail",
            as_type="guardrail",
            level=level,
        ) as span:
            span.update(
                output={
                    "status": req.output_guardrail_status,
                    "issues": req.output_guardrail_issues,
                    "answer_content_logged": False,
                }
            )

    @staticmethod
    def _add_cache_store_span(root: Any, req: UsageLogRequest, stages: list[str]) -> None:
        should_store = (
            req.cache_status == "miss"
            and req.status == "completed"
            and req.output_guardrail_status == "passed"
            and _provider_called(req)
        )
        if not should_store:
            return
        stages.append("cache_store")
        with root.start_as_current_observation(
            name="cache_store",
            as_type="tool",
            metadata={"sensitive_request": req.privacy_enforced},
        ) as span:
            span.update(output={"attempted": True, "content_logged": False})

    @staticmethod
    def _add_usage_log_span(root: Any, req: UsageLogRequest, stages: list[str]) -> None:
        stages.append("usage_log")
        with root.start_as_current_observation(
            name="usage_log",
            as_type="tool",
        ) as span:
            span.update(
                output={
                    "logged": True,
                    "request_id": req.request_id,
                    "raw_prompt_stored": False,
                }
            )

    def shutdown(self) -> None:
        if self._client is None:
            return
        shutdown = getattr(self._client, "shutdown", None)
        if callable(shutdown):
            shutdown()


@lru_cache(maxsize=1)
def get_trace_exporter() -> LangfuseTraceExporter:
    return LangfuseTraceExporter()
