"""Unit tests for usage persistence and analytics."""

import os
import sqlite3
import tempfile

import pytest
from pydantic import ValidationError

from main import AgentRunRequest, agent_run
from usage.analytics import get_recent, get_summary
from usage.database import init_db
from usage.repository import log_usage, prompt_fingerprint
from usage.schemas import UsageLogRequest


@pytest.fixture
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)



@pytest.fixture
def sample_logs(tmp_db):
    log_usage(UsageLogRequest(
        request_id="r-model",
        dept_id="support",
        prompt="reset password help",
        task_type="support_request",
        complexity_level="low",
        guardrail_status="passed",
        cache_status="miss",
        status="completed",
        provider="ollama",
        model="llama3.1:latest",
        requested_tier="cheap",
        executed_tier="cheap",
        actual_input_tokens=10,
        actual_output_tokens=20,
        actual_total_tokens=30,
        actual_cost=0.0,
        cost_calculation_status="local_zero_api_cost",
        latency_ms=1000,
        savings_source="model_routing",
        estimated_baseline_cost=0.001,
        estimated_optimized_cost=0.0,
        estimated_savings=0.001,
        actual_cost_saved=0.001,
        actual_execution_attempt_count=1,
    ), db_path=tmp_db)

    log_usage(UsageLogRequest(
        request_id="r-cache",
        dept_id="support",
        policy_mode="conservative",
        prompt="cached query",
        cache_status="hit",
        status="completed",
        provider="not called — semantic cache",
        requested_tier="cache",
        executed_tier="cache",
        savings_source="semantic_cache",
        estimated_baseline_cost=0.0005,
        estimated_savings=0.0005,
    ), db_path=tmp_db)

    log_usage(UsageLogRequest(
        request_id="r-block",
        dept_id="sales",
        policy_mode="aggressive",
        prompt="off topic",
        guardrail_status="blocked",
        cache_status="skipped",
        status="blocked",
        provider="not called — guardrail block",
        savings_source="guardrails_cost_governance",
        estimated_baseline_cost=0.0003,
        estimated_savings=0.0003,
    ), db_path=tmp_db)

    return tmp_db


def test_database_initialization(tmp_db):
    with sqlite3.connect(tmp_db) as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    assert "requests" in tables
    assert "model_executions" in tables
    assert "optimization_actions" in tables
    assert "output_guardrail_results" in tables
    assert "observability_exports" in tables


def test_request_logging(tmp_db):
    resp = log_usage(UsageLogRequest(
        request_id="r1",
        dept_id="support",
        prompt="hello world",
        savings_source="model_routing",
    ), db_path=tmp_db)
    assert resp.logged is True
    assert resp.request_id == "r1"
    with sqlite3.connect(tmp_db) as conn:
        row = conn.execute("SELECT * FROM requests WHERE request_id='r1'").fetchone()
    assert row is not None


def test_idempotent_duplicate_log(tmp_db):
    req = UsageLogRequest(request_id="r-dup", dept_id="support", prompt="same prompt")
    first = log_usage(req, db_path=tmp_db)
    second = log_usage(req, db_path=tmp_db)
    assert first.duplicate is False
    assert second.duplicate is True
    with sqlite3.connect(tmp_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM requests WHERE request_id='r-dup'").fetchone()[0]
    assert count == 1


def test_model_execution_persistence(tmp_db):
    log_usage(UsageLogRequest(
        request_id="r-exec",
        prompt="test",
        provider="ollama",
        model="llama3.1:latest",
        actual_total_tokens=50,
        actual_execution_attempt_count=1,
    ), db_path=tmp_db)
    with sqlite3.connect(tmp_db) as conn:
        row = conn.execute(
            "SELECT provider, actual_total_tokens FROM model_executions WHERE request_id='r-exec'"
        ).fetchone()
    assert row[0] == "ollama"
    assert row[1] == 50


def test_cache_hit_persistence(sample_logs):
    summary = get_summary(period_days=30, db_path=sample_logs)
    assert summary.requests_by_source.get("semantic_cache", 0) >= 1


def test_guardrail_block_persistence(sample_logs):
    summary = get_summary(period_days=30, db_path=sample_logs)
    assert summary.blocked_requests >= 1
    assert summary.requests_by_source.get("guardrails_cost_governance", 0) >= 1


def test_nullable_actual_cost(tmp_db):
    log_usage(UsageLogRequest(
        request_id="r-null-cost",
        prompt="test",
        provider="openai",
        actual_cost=None,
        cost_calculation_status="pricing_not_configured",
    ), db_path=tmp_db)
    with sqlite3.connect(tmp_db) as conn:
        row = conn.execute(
            "SELECT actual_cost FROM model_executions WHERE request_id='r-null-cost'"
        ).fetchone()
    assert row[0] is None


def test_summary_totals(sample_logs):
    s = get_summary(period_days=30, db_path=sample_logs)
    assert s.total_requests == 3
    assert s.total_savings == pytest.approx(0.0018)
    assert s.total_modeled_cost_avoidance == s.total_savings
    assert s.total_actual_api_cost == s.total_actual_cost == 0
    assert s.total_estimated_baseline_cost == pytest.approx(0.0018)
    assert s.total_estimated_optimized_cost == 0
    assert s.actual_cost_savings_request_count == 1
    assert s.estimated_savings_request_count == 2
    assert s.unknown_actual_cost_request_count == 0
    assert s.cost_avoidance_basis == "actual_api_cost_when_available_else_estimated_cost"


def test_cache_hit_rate(sample_logs):
    s = get_summary(period_days=30, db_path=sample_logs)
    assert s.cache_hit_rate == pytest.approx(1 / 3, abs=0.01)


def test_guardrail_block_rate(sample_logs):
    s = get_summary(period_days=30, db_path=sample_logs)
    assert s.guardrail_block_rate == pytest.approx(1 / 3, abs=0.01)


def test_savings_by_source(sample_logs):
    s = get_summary(period_days=30, db_path=sample_logs)
    assert s.savings_by_source.get("model_routing", 0) > 0
    assert s.savings_by_source.get("semantic_cache", 0) > 0


def test_policy_mode_breakdowns(sample_logs):
    s = get_summary(period_days=30, db_path=sample_logs)
    assert s.requests_by_policy_mode == {
        "conservative": 1,
        "balanced": 1,
        "aggressive": 1,
    }
    assert s.savings_by_policy_mode["balanced"] == pytest.approx(0.001)
    assert s.savings_by_policy_mode["conservative"] == pytest.approx(0.0005)
    assert s.savings_by_policy_mode["aggressive"] == pytest.approx(0.0003)


def test_department_filtering(sample_logs):
    s = get_summary(period_days=30, dept_id="sales", db_path=sample_logs)
    assert s.total_requests == 1


def test_recent_excludes_prompts(sample_logs):
    recent = get_recent(limit=10, db_path=sample_logs)
    dumped = str(recent.model_dump())
    assert "reset password" not in dumped
    assert "cached query" not in dumped
    assert recent.count == 3
    assert {item.policy_mode for item in recent.items} == {
        "conservative",
        "balanced",
        "aggressive",
    }
    assert {item.savings_basis for item in recent.items} == {
        "actual_api_cost",
        "estimated_cost",
    }


def test_prompt_fingerprint_deterministic():
    a = prompt_fingerprint("  Hello   World ")
    b = prompt_fingerprint("hello world")
    assert a == b
    assert len(a) == 64


def test_sensitive_input_not_stored_raw(tmp_db):
    sensitive = "My email is secret@example.com"
    log_usage(UsageLogRequest(
        request_id="r-pii",
        prompt=sensitive,
        guardrail_status="passed_with_redaction",
        privacy_enforced=True,
        provider="ollama",
        savings_source="model_routing",
    ), db_path=tmp_db)
    with sqlite3.connect(tmp_db) as conn:
        cols = [d[1] for d in conn.execute("PRAGMA table_info(requests)").fetchall()]
        assert "prompt" not in cols
        fp = conn.execute(
            "SELECT prompt_fingerprint FROM requests WHERE request_id='r-pii'"
        ).fetchone()[0]
    assert sensitive not in fp
    assert len(fp) == 64


def test_savings_not_double_counted(tmp_db):
    log_usage(UsageLogRequest(
        request_id="r-savings",
        prompt="x",
        estimated_savings=0.01,
        actual_cost_saved=0.008,
        savings_source="model_routing",
        estimated_baseline_cost=0.01,
    ), db_path=tmp_db)
    s = get_summary(period_days=30, db_path=sample_logs if False else tmp_db)
    # Uses actual_cost_saved (0.008) not estimated + actual
    assert s.total_savings == pytest.approx(0.008, abs=0.0001)


def test_roi_not_falsely_calculated(sample_logs):
    s = get_summary(period_days=30, db_path=sample_logs)
    assert s.roi_percentage is None
    assert s.roi_status == "operating_cost_not_modeled"
    assert s.roi_basis == "not_calculated"
    assert s.operating_cost_usd is None
    assert s.savings_percentage is not None


def test_roi_uses_explicit_operating_cost(sample_logs):
    s = get_summary(
        period_days=30,
        operating_cost_usd=0.001,
        db_path=sample_logs,
    )
    assert s.operating_cost_usd == 0.001
    assert s.roi_percentage == pytest.approx(80.0)
    assert s.roi_status == "calculated_from_supplied_operating_cost"
    assert s.roi_basis == "modeled_cost_avoidance_minus_supplied_operating_cost"


@pytest.mark.parametrize("operating_cost", [0, -1, float("nan"), float("inf")])
def test_roi_rejects_invalid_operating_cost(sample_logs, operating_cost):
    with pytest.raises(ValueError, match="finite and greater than zero"):
        get_summary(
            period_days=30,
            operating_cost_usd=operating_cost,
            db_path=sample_logs,
        )


def test_premium_usage_counts_execution_separately(tmp_db):
    log_usage(UsageLogRequest(
        request_id="r-premium-request",
        provider="ollama",
        requested_tier="premium",
        executed_tier="cheap",
        actual_cost=0,
        actual_execution_attempt_count=1,
    ), db_path=tmp_db)
    summary = get_summary(period_days=30, db_path=tmp_db)
    assert summary.premium_usage_rate == 0
    assert summary.premium_requested_rate == 1


def test_unknown_actual_cost_counts_real_executions_only(tmp_db):
    log_usage(UsageLogRequest(
        request_id="r-unknown-cost",
        provider="openai",
        requested_tier="balanced",
        executed_tier="balanced",
        actual_execution_attempt_count=1,
        actual_cost=None,
    ), db_path=tmp_db)
    log_usage(UsageLogRequest(
        request_id="r-no-execution",
        provider="not called — semantic cache",
        requested_tier="cache",
        executed_tier="cache",
    ), db_path=tmp_db)
    summary = get_summary(period_days=30, db_path=tmp_db)
    assert summary.unknown_actual_cost_request_count == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("actual_input_tokens", -1),
        ("actual_output_tokens", -1),
        ("actual_total_tokens", -1),
        ("actual_cost", -0.01),
        ("latency_ms", -1),
        ("estimated_baseline_cost", -0.01),
        ("estimated_optimized_cost", -0.01),
        ("estimated_savings", -0.01),
        ("actual_cost_saved", -0.01),
    ],
)
def test_usage_log_rejects_negative_metrics(field, value):
    with pytest.raises(ValidationError):
        UsageLogRequest(request_id="r-invalid", **{field: value})


def test_usage_log_rejects_invalid_policy_mode():
    with pytest.raises(ValidationError):
        UsageLogRequest(request_id="r-invalid", policy_mode="banana")


def test_usage_log_canonicalizes_policy_mode():
    req = UsageLogRequest(request_id="r-valid", policy_mode=" Aggressive ")
    assert req.policy_mode == "aggressive"


def test_usage_log_rejects_inconsistent_token_total():
    with pytest.raises(ValidationError, match="must equal input plus output"):
        UsageLogRequest(
            request_id="r-token-mismatch",
            actual_input_tokens=2,
            actual_output_tokens=3,
            actual_total_tokens=4,
        )


def test_agent_request_rejects_invalid_inputs():
    with pytest.raises(ValidationError):
        AgentRunRequest(policy_mode="banana")
    with pytest.raises(ValidationError):
        AgentRunRequest(estimated_tokens=-1)
    with pytest.raises(ValidationError):
        AgentRunRequest(max_cost=-1)


def test_agent_response_exposes_canonical_policy_mode():
    response = agent_run(AgentRunRequest(prompt="Explain input validation.", policy_mode="Conservative"))
    assert response["policy_mode"] == "conservative"
