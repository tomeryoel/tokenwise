"""Unit tests for usage persistence and analytics."""

import os
import sqlite3
import tempfile

import pytest

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
    assert s.total_savings > 0


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


def test_department_filtering(sample_logs):
    s = get_summary(period_days=30, dept_id="sales", db_path=sample_logs)
    assert s.total_requests == 1


def test_recent_excludes_prompts(sample_logs):
    recent = get_recent(limit=10, db_path=sample_logs)
    dumped = str(recent.model_dump())
    assert "reset password" not in dumped
    assert "cached query" not in dumped
    assert recent.count == 3


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
    assert s.savings_percentage is not None
