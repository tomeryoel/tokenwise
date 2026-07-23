"""Usage analytics aggregation queries."""

from __future__ import annotations

import math

from usage.database import get_connection
from usage.schemas import RecentRequestItem, UsageRecentResponse, UsageSummaryResponse

VALID_SOURCES = (
    "guardrails_cost_governance",
    "semantic_cache",
    "model_routing",
    "prompt_compression",
    "unknown",
)
POLICY_MODES = ("conservative", "balanced", "aggressive")
COST_AVOIDANCE_BASIS = "actual_api_cost_when_available_else_estimated_cost"
ROI_BASIS = "modeled_cost_avoidance_minus_supplied_operating_cost"


def _period_filter(days: int) -> str:
    return f"-{int(days)} days"


def _scope_filter(
    *,
    period_days: int | None = None,
    organization_id: str | None = None,
    include_legacy: bool = False,
    user_id: str | None = None,
    dept_id: str | None = None,
) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []
    if period_days is not None:
        clauses.append("datetime(r.created_at) >= datetime('now', ?)")
        params.append(_period_filter(period_days))
    if organization_id:
        if include_legacy:
            clauses.append(
                "(r.organization_id = ? OR r.organization_id = 'legacy-local')"
            )
        else:
            clauses.append("r.organization_id = ?")
        params.append(organization_id)
    if user_id:
        clauses.append("r.user_id = ?")
        params.append(user_id)
    if dept_id:
        clauses.append("r.dept_id = ?")
        params.append(dept_id)
    return " AND ".join(clauses) if clauses else "1 = 1", params


def get_summary(
    period_days: int = 30,
    organization_id: str | None = None,
    include_legacy: bool = False,
    user_id: str | None = None,
    dept_id: str | None = None,
    operating_cost_usd: float | None = None,
    db_path: str | None = None,
) -> UsageSummaryResponse:
    period_days = max(1, min(period_days, 365))
    if operating_cost_usd is not None and (
        not math.isfinite(operating_cost_usd) or operating_cost_usd <= 0
    ):
        raise ValueError("operating_cost_usd must be finite and greater than zero")
    scope_clause, params = _scope_filter(
        period_days=period_days,
        organization_id=organization_id,
        include_legacy=include_legacy,
        user_id=user_id,
        dept_id=dept_id,
    )

    with get_connection(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT
                COUNT(*) AS total_requests,
                SUM(CASE WHEN r.status = 'completed' THEN 1 ELSE 0 END) AS completed_requests,
                SUM(CASE WHEN r.guardrail_status = 'blocked' OR r.status = 'blocked' THEN 1 ELSE 0 END) AS blocked_requests,
                SUM(CASE WHEN r.cache_status = 'hit' THEN 1 ELSE 0 END) AS cache_hits,
                SUM(COALESCE(m.actual_cost, 0)) AS total_actual_cost,
                SUM(COALESCE(o.estimated_baseline_cost, 0)) AS total_baseline,
                SUM(COALESCE(o.estimated_optimized_cost, 0)) AS total_optimized,
                SUM(
                    CASE
                        WHEN o.actual_cost_saved IS NOT NULL THEN o.actual_cost_saved
                        ELSE COALESCE(o.estimated_savings, 0)
                    END
                ) AS total_savings,
                SUM(CASE WHEN o.actual_cost_saved IS NOT NULL THEN 1 ELSE 0 END) AS actual_savings_count,
                SUM(CASE WHEN o.actual_cost_saved IS NULL THEN 1 ELSE 0 END) AS estimated_savings_count,
                SUM(
                    CASE
                        WHEN (
                            COALESCE(m.actual_execution_attempt_count, 0) > 0
                            OR COALESCE(m.actual_total_tokens, 0) > 0
                        ) AND m.actual_cost IS NULL THEN 1
                        ELSE 0
                    END
                ) AS unknown_actual_cost_count,
                SUM(CASE WHEN m.used_fallback = 1 THEN 1 ELSE 0 END) AS fallback_count,
                SUM(CASE WHEN m.executed_tier = 'premium' THEN 1 ELSE 0 END) AS premium_executed_count,
                SUM(CASE WHEN m.requested_tier = 'premium' THEN 1 ELSE 0 END) AS premium_requested_count,
                AVG(CASE WHEN m.latency_ms > 0 THEN m.latency_ms END) AS avg_latency,
                SUM(COALESCE(m.actual_input_tokens, 0)) AS total_input_tokens,
                SUM(COALESCE(m.actual_output_tokens, 0)) AS total_output_tokens
            FROM requests r
            LEFT JOIN model_executions m ON m.request_id = r.request_id
            LEFT JOIN optimization_actions o ON o.request_id = r.request_id
            WHERE {scope_clause}
            """,
            params,
        ).fetchone()

        total = int(row["total_requests"] or 0)
        blocked = int(row["blocked_requests"] or 0)
        cache_hits = int(row["cache_hits"] or 0)
        total_baseline = float(row["total_baseline"] or 0)
        total_savings = float(row["total_savings"] or 0)

        requests_by_source: dict[str, int] = {s: 0 for s in VALID_SOURCES}
        savings_by_source: dict[str, float] = {s: 0.0 for s in VALID_SOURCES}
        requests_by_policy_mode: dict[str, int] = {mode: 0 for mode in POLICY_MODES}
        savings_by_policy_mode: dict[str, float] = {mode: 0.0 for mode in POLICY_MODES}

        source_rows = conn.execute(
            f"""
            SELECT o.savings_source, COUNT(*) AS cnt,
                SUM(
                    CASE
                        WHEN o.actual_cost_saved IS NOT NULL THEN o.actual_cost_saved
                        ELSE COALESCE(o.estimated_savings, 0)
                    END
                ) AS savings
            FROM requests r
            JOIN optimization_actions o ON o.request_id = r.request_id
            WHERE {scope_clause}
            GROUP BY o.savings_source
            """,
            params,
        ).fetchall()

        for sr in source_rows:
            src = sr["savings_source"] or "unknown"
            if src not in requests_by_source:
                requests_by_source[src] = 0
                savings_by_source[src] = 0.0
            requests_by_source[src] = int(sr["cnt"])
            savings_by_source[src] = round(float(sr["savings"] or 0), 8)

        policy_rows = conn.execute(
            f"""
            SELECT r.policy_mode, COUNT(*) AS cnt,
                SUM(
                    CASE
                        WHEN o.actual_cost_saved IS NOT NULL THEN o.actual_cost_saved
                        ELSE COALESCE(o.estimated_savings, 0)
                    END
                ) AS savings
            FROM requests r
            LEFT JOIN optimization_actions o ON o.request_id = r.request_id
            WHERE {scope_clause}
            GROUP BY r.policy_mode
            """,
            params,
        ).fetchall()

        for pr in policy_rows:
            mode = pr["policy_mode"] or "balanced"
            if mode not in requests_by_policy_mode:
                requests_by_policy_mode[mode] = 0
                savings_by_policy_mode[mode] = 0.0
            requests_by_policy_mode[mode] = int(pr["cnt"])
            savings_by_policy_mode[mode] = round(float(pr["savings"] or 0), 8)

    savings_pct = (
        round((total_savings / total_baseline) * 100, 2) if total_baseline > 0 else None
    )
    roi_percentage = None
    roi_status = "operating_cost_not_modeled"
    roi_basis = "not_calculated"
    if operating_cost_usd is not None:
        roi_percentage = round(
            ((total_savings - operating_cost_usd) / operating_cost_usd) * 100,
            2,
        )
        roi_status = "calculated_from_supplied_operating_cost"
        roi_basis = ROI_BASIS

    total_actual_api_cost = round(float(row["total_actual_cost"] or 0), 8)
    total_optimized = round(float(row["total_optimized"] or 0), 8)
    modeled_cost_avoidance = round(total_savings, 8)

    return UsageSummaryResponse(
        period_days=period_days,
        total_requests=total,
        completed_requests=int(row["completed_requests"] or 0),
        blocked_requests=blocked,
        total_actual_cost=total_actual_api_cost,
        total_actual_api_cost=total_actual_api_cost,
        total_estimated_baseline_cost=round(total_baseline, 8),
        total_estimated_optimized_cost=total_optimized,
        total_savings=modeled_cost_avoidance,
        total_modeled_cost_avoidance=modeled_cost_avoidance,
        cost_avoidance_basis=COST_AVOIDANCE_BASIS,
        actual_cost_savings_request_count=int(row["actual_savings_count"] or 0),
        estimated_savings_request_count=int(row["estimated_savings_count"] or 0),
        unknown_actual_cost_request_count=int(row["unknown_actual_cost_count"] or 0),
        savings_percentage=savings_pct,
        operating_cost_usd=operating_cost_usd,
        roi_percentage=roi_percentage,
        roi_status=roi_status,
        roi_basis=roi_basis,
        cache_hit_rate=round(cache_hits / total, 4) if total else 0.0,
        guardrail_block_rate=round(blocked / total, 4) if total else 0.0,
        premium_usage_rate=(
            round(int(row["premium_executed_count"] or 0) / total, 4) if total else 0.0
        ),
        premium_requested_rate=(
            round(int(row["premium_requested_count"] or 0) / total, 4) if total else 0.0
        ),
        fallback_rate=round(int(row["fallback_count"] or 0) / total, 4) if total else 0.0,
        average_latency_ms=round(float(row["avg_latency"] or 0), 2),
        total_input_tokens=int(row["total_input_tokens"] or 0),
        total_output_tokens=int(row["total_output_tokens"] or 0),
        requests_by_source=requests_by_source,
        savings_by_source={k: round(v, 8) for k, v in savings_by_source.items()},
        requests_by_policy_mode=requests_by_policy_mode,
        savings_by_policy_mode={k: round(v, 8) for k, v in savings_by_policy_mode.items()},
    )


def get_recent(
    limit: int = 20,
    organization_id: str | None = None,
    include_legacy: bool = False,
    user_id: str | None = None,
    dept_id: str | None = None,
    db_path: str | None = None,
) -> UsageRecentResponse:
    limit = max(1, min(limit, 100))
    scope_clause, params = _scope_filter(
        organization_id=organization_id,
        include_legacy=include_legacy,
        user_id=user_id,
        dept_id=dept_id,
    )
    params.append(limit)

    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                r.request_id, r.created_at, r.organization_id, r.user_id,
                r.dept_id, r.policy_mode, r.task_type, r.status,
                r.guardrail_status, r.cache_status,
                m.provider, m.model, m.requested_tier, m.executed_tier,
                COALESCE(m.actual_total_tokens, 0) AS actual_total_tokens,
                COALESCE(m.latency_ms, 0) AS latency_ms,
                o.savings_source,
                CASE
                    WHEN o.actual_cost_saved IS NOT NULL THEN o.actual_cost_saved
                    ELSE COALESCE(o.estimated_savings, 0)
                END AS savings_amount,
                CASE
                    WHEN o.actual_cost_saved IS NOT NULL THEN 'actual_api_cost'
                    ELSE 'estimated_cost'
                END AS savings_basis
            FROM requests r
            LEFT JOIN model_executions m ON m.request_id = r.request_id
            LEFT JOIN optimization_actions o ON o.request_id = r.request_id
            WHERE {scope_clause}
            ORDER BY r.created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    items = [
        RecentRequestItem(
            request_id=row["request_id"],
            created_at=row["created_at"],
            organization_id=row["organization_id"],
            user_id=row["user_id"],
            dept_id=row["dept_id"],
            policy_mode=row["policy_mode"],
            task_type=row["task_type"],
            status=row["status"],
            guardrail_status=row["guardrail_status"],
            cache_status=row["cache_status"],
            provider=row["provider"],
            model=row["model"],
            requested_tier=row["requested_tier"],
            executed_tier=row["executed_tier"],
            actual_total_tokens=int(row["actual_total_tokens"]),
            latency_ms=int(row["latency_ms"]),
            savings_source=row["savings_source"] or "unknown",
            savings_amount=round(float(row["savings_amount"] or 0), 8),
            savings_basis=row["savings_basis"],
        )
        for row in rows
    ]

    return UsageRecentResponse(items=items, count=len(items))
