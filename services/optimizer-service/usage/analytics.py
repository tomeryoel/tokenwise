"""Usage analytics aggregation queries."""

from __future__ import annotations

from usage.database import get_connection
from usage.schemas import RecentRequestItem, UsageRecentResponse, UsageSummaryResponse

VALID_SOURCES = (
    "guardrails_cost_governance",
    "semantic_cache",
    "model_routing",
    "prompt_compression",
    "unknown",
)


def _period_filter(days: int) -> str:
    return f"-{int(days)} days"


def get_summary(
    period_days: int = 30,
    dept_id: str | None = None,
    db_path: str | None = None,
) -> UsageSummaryResponse:
    period_days = max(1, min(period_days, 365))
    period_clause = "datetime(r.created_at) >= datetime('now', ?)"
    params: list = [_period_filter(period_days)]

    dept_clause = ""
    if dept_id:
        dept_clause = " AND r.dept_id = ?"
        params.append(dept_id)

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
                SUM(CASE WHEN m.used_fallback = 1 THEN 1 ELSE 0 END) AS fallback_count,
                SUM(CASE WHEN m.executed_tier = 'premium' OR m.requested_tier = 'premium' THEN 1 ELSE 0 END) AS premium_count,
                AVG(CASE WHEN m.latency_ms > 0 THEN m.latency_ms END) AS avg_latency,
                SUM(COALESCE(m.actual_input_tokens, 0)) AS total_input_tokens,
                SUM(COALESCE(m.actual_output_tokens, 0)) AS total_output_tokens
            FROM requests r
            LEFT JOIN model_executions m ON m.request_id = r.request_id
            LEFT JOIN optimization_actions o ON o.request_id = r.request_id
            WHERE {period_clause}{dept_clause}
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
            WHERE {period_clause}{dept_clause}
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

    savings_pct = (
        round((total_savings / total_baseline) * 100, 2) if total_baseline > 0 else None
    )

    return UsageSummaryResponse(
        period_days=period_days,
        total_requests=total,
        completed_requests=int(row["completed_requests"] or 0),
        blocked_requests=blocked,
        total_actual_cost=round(float(row["total_actual_cost"] or 0), 8),
        total_estimated_baseline_cost=round(total_baseline, 8),
        total_savings=round(total_savings, 8),
        savings_percentage=savings_pct,
        roi_percentage=None,
        roi_status="operating_cost_not_modeled",
        cache_hit_rate=round(cache_hits / total, 4) if total else 0.0,
        guardrail_block_rate=round(blocked / total, 4) if total else 0.0,
        premium_usage_rate=round(int(row["premium_count"] or 0) / total, 4) if total else 0.0,
        fallback_rate=round(int(row["fallback_count"] or 0) / total, 4) if total else 0.0,
        average_latency_ms=round(float(row["avg_latency"] or 0), 2),
        total_input_tokens=int(row["total_input_tokens"] or 0),
        total_output_tokens=int(row["total_output_tokens"] or 0),
        requests_by_source=requests_by_source,
        savings_by_source={k: round(v, 8) for k, v in savings_by_source.items()},
    )


def get_recent(
    limit: int = 20,
    dept_id: str | None = None,
    db_path: str | None = None,
) -> UsageRecentResponse:
    limit = max(1, min(limit, 100))
    params: list = []
    dept_clause = ""
    if dept_id:
        dept_clause = " WHERE r.dept_id = ?"
        params.append(dept_id)

    params.append(limit)

    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                r.request_id, r.created_at, r.dept_id, r.task_type, r.status,
                r.guardrail_status, r.cache_status,
                m.provider, m.model, m.requested_tier, m.executed_tier,
                COALESCE(m.actual_total_tokens, 0) AS actual_total_tokens,
                COALESCE(m.latency_ms, 0) AS latency_ms,
                o.savings_source,
                CASE
                    WHEN o.actual_cost_saved IS NOT NULL THEN o.actual_cost_saved
                    ELSE COALESCE(o.estimated_savings, 0)
                END AS savings_amount
            FROM requests r
            LEFT JOIN model_executions m ON m.request_id = r.request_id
            LEFT JOIN optimization_actions o ON o.request_id = r.request_id
            {dept_clause}
            ORDER BY r.created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    items = [
        RecentRequestItem(
            request_id=row["request_id"],
            created_at=row["created_at"],
            dept_id=row["dept_id"],
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
        )
        for row in rows
    ]

    return UsageRecentResponse(items=items, count=len(items))
