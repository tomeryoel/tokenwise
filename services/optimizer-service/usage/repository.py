"""Usage data persistence with idempotent request logging."""

from __future__ import annotations

import hashlib
import json
import re

from usage.database import get_connection
from usage.schemas import UsageLogRequest, UsageLogResponse


def normalize_prompt_for_fingerprint(prompt: str) -> str:
    """Normalize prompt text before hashing (no raw storage)."""
    text = (prompt or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def prompt_fingerprint(prompt: str) -> str:
    normalized = normalize_prompt_for_fingerprint(prompt)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _primary_savings(req: UsageLogRequest) -> float:
    """Single primary savings metric per request (no double-counting)."""
    if req.actual_cost_saved is not None:
        return max(0.0, req.actual_cost_saved)
    return max(0.0, req.estimated_savings)


def log_usage(req: UsageLogRequest, db_path: str | None = None) -> UsageLogResponse:
    """Log a terminal request path. Idempotent on request_id via upsert.

    Strategy:
    - requests: INSERT ... ON CONFLICT(request_id) DO UPDATE (refresh metadata)
    - child tables: INSERT ... ON CONFLICT(request_id) DO UPDATE (replace row)
    - No duplicate request rows on n8n retries
    """
    fingerprint = prompt_fingerprint(req.prompt)
    metadata = {}
    if req.output_guardrail_status == "blocked":
        metadata["output_guardrail_intervention"] = True
    if req.output_guardrail_issues:
        metadata["output_guardrail_issues"] = req.output_guardrail_issues

    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM requests WHERE request_id = ?",
            (req.request_id,),
        ).fetchone()
        duplicate = existing is not None

        conn.execute(
            """
            INSERT INTO requests (
                request_id, dept_id, policy_mode, prompt_fingerprint,
                task_type, complexity_level, guardrail_status, guardrail_reason,
                detected_risk_type, cache_status, cache_confidence, graph_path, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(request_id) DO UPDATE SET
                dept_id = excluded.dept_id,
                policy_mode = excluded.policy_mode,
                prompt_fingerprint = excluded.prompt_fingerprint,
                task_type = excluded.task_type,
                complexity_level = excluded.complexity_level,
                guardrail_status = excluded.guardrail_status,
                guardrail_reason = excluded.guardrail_reason,
                detected_risk_type = excluded.detected_risk_type,
                cache_status = excluded.cache_status,
                cache_confidence = excluded.cache_confidence,
                graph_path = excluded.graph_path,
                status = excluded.status
            """,
            (
                req.request_id,
                req.dept_id,
                req.policy_mode,
                fingerprint,
                req.task_type,
                req.complexity_level,
                req.guardrail_status,
                req.guardrail_reason,
                req.detected_risk_type,
                req.cache_status,
                req.cache_confidence,
                req.graph_path,
                req.status,
            ),
        )

        has_execution = (
            req.provider
            and req.provider not in ("not called — semantic cache", "not called — guardrail block", "none", "-")
            and req.actual_execution_attempt_count > 0
        ) or req.actual_total_tokens > 0

        if has_execution or req.provider:
            conn.execute(
                """
                INSERT INTO model_executions (
                    request_id, provider, model, requested_tier, executed_tier,
                    actual_input_tokens, actual_output_tokens, actual_total_tokens,
                    actual_cost, cost_calculation_status, latency_ms,
                    used_fallback, fallback_reason, privacy_enforced,
                    actual_execution_attempt_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET
                    provider = excluded.provider,
                    model = excluded.model,
                    requested_tier = excluded.requested_tier,
                    executed_tier = excluded.executed_tier,
                    actual_input_tokens = excluded.actual_input_tokens,
                    actual_output_tokens = excluded.actual_output_tokens,
                    actual_total_tokens = excluded.actual_total_tokens,
                    actual_cost = excluded.actual_cost,
                    cost_calculation_status = excluded.cost_calculation_status,
                    latency_ms = excluded.latency_ms,
                    used_fallback = excluded.used_fallback,
                    fallback_reason = excluded.fallback_reason,
                    privacy_enforced = excluded.privacy_enforced,
                    actual_execution_attempt_count = excluded.actual_execution_attempt_count
                """,
                (
                    req.request_id,
                    req.provider,
                    req.model,
                    req.requested_tier,
                    req.executed_tier,
                    req.actual_input_tokens,
                    req.actual_output_tokens,
                    req.actual_total_tokens,
                    req.actual_cost,
                    req.cost_calculation_status,
                    req.latency_ms,
                    1 if req.used_fallback else 0,
                    req.fallback_reason,
                    1 if req.privacy_enforced else 0,
                    req.actual_execution_attempt_count,
                ),
            )
        else:
            conn.execute("DELETE FROM model_executions WHERE request_id = ?", (req.request_id,))

        conn.execute(
            """
            INSERT INTO optimization_actions (
                request_id, action_type, savings_source, savings_reason,
                estimated_baseline_cost, estimated_optimized_cost,
                estimated_savings, actual_cost_saved, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(request_id) DO UPDATE SET
                action_type = excluded.action_type,
                savings_source = excluded.savings_source,
                savings_reason = excluded.savings_reason,
                estimated_baseline_cost = excluded.estimated_baseline_cost,
                estimated_optimized_cost = excluded.estimated_optimized_cost,
                estimated_savings = excluded.estimated_savings,
                actual_cost_saved = excluded.actual_cost_saved,
                metadata_json = excluded.metadata_json
            """,
            (
                req.request_id,
                "optimization",
                req.savings_source,
                req.savings_reason,
                req.estimated_baseline_cost,
                req.estimated_optimized_cost,
                req.estimated_savings,
                req.actual_cost_saved,
                json.dumps(metadata) if metadata else None,
            ),
        )

        conn.execute(
            """
            INSERT INTO output_guardrail_results (request_id, status, issues_json)
            VALUES (?, ?, ?)
            ON CONFLICT(request_id) DO UPDATE SET
                status = excluded.status,
                issues_json = excluded.issues_json
            """,
            (
                req.request_id,
                req.output_guardrail_status,
                json.dumps(req.output_guardrail_issues) if req.output_guardrail_issues else None,
            ),
        )

        conn.commit()

    return UsageLogResponse(logged=True, request_id=req.request_id, duplicate=duplicate)
