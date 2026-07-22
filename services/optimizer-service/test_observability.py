"""Focused tests for privacy-safe, idempotent Langfuse tracing."""

from __future__ import annotations

import json
import os
import tempfile

import main as optimizer_main
from observability.config import ObservabilityConfig
from observability.exporter import LangfuseTraceExporter
from observability.repository import get_export_counts, get_export_record, record_export_attempt
from observability.schemas import TraceExportResult
from usage.database import init_db
from usage.schemas import UsageLogRequest, UsageLogResponse


class FakeObservation:
    def __init__(self, records: list[dict], kwargs: dict) -> None:
        self.records = records
        self.record = {"create": kwargs, "updates": []}
        self.records.append(self.record)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def start_as_current_observation(self, **kwargs):
        return FakeObservation(self.records, kwargs)

    def update(self, **kwargs):
        self.record["updates"].append(kwargs)


class FakeLangfuseClient:
    def __init__(self, trace_base_url: str = "http://langfuse.local") -> None:
        self.records: list[dict] = []
        self.flush_count = 0
        self.shutdown_count = 0
        self.trace_base_url = trace_base_url

    def create_trace_id(self, seed: str) -> str:
        assert seed
        return "a" * 32

    def start_as_current_observation(self, **kwargs):
        return FakeObservation(self.records, kwargs)

    def flush(self) -> None:
        self.flush_count += 1

    def get_trace_url(self, trace_id: str) -> str:
        return f"{self.trace_base_url}/trace/{trace_id}"

    def shutdown(self) -> None:
        self.shutdown_count += 1


def enabled_config() -> ObservabilityConfig:
    return ObservabilityConfig(
        requested_enabled=True,
        public_key="lf_pk_test",
        secret_key="lf_sk_test",
        base_url="http://langfuse.local",
        environment="test",
        release="test-release",
        flush_on_export=True,
    )


def observation_names(client: FakeLangfuseClient) -> list[str]:
    return [record["create"]["name"] for record in client.records]


def test_model_path_exports_expected_spans_and_usage():
    client = FakeLangfuseClient()
    exporter = LangfuseTraceExporter(config=enabled_config(), client=client)
    req = UsageLogRequest(
        request_id="r-model",
        dept_id="support",
        policy_mode="balanced",
        prompt="How can MomiHelm reduce model cost?",
        task_type="product_question",
        guardrail_status="passed",
        cache_status="miss",
        graph_path="standard_optimization_path",
        provider="ollama",
        model="llama3.1:latest",
        requested_tier="cheap",
        executed_tier="cheap",
        actual_input_tokens=11,
        actual_output_tokens=17,
        actual_total_tokens=28,
        actual_cost=0.0,
        latency_ms=321,
        actual_execution_attempt_count=1,
        savings_source="model_routing",
        savings_reason="cheaper_model_selected",
        estimated_baseline_cost=0.01,
        estimated_optimized_cost=0.0,
        estimated_savings=0.01,
        output_guardrail_status="passed",
    )

    result = exporter.export_usage(req)

    assert result.exported is True
    assert result.trace_id == "a" * 32
    assert client.flush_count == 1
    assert observation_names(client) == [
        "tokenwise_request",
        "input_guardrail",
        "semantic_cache_lookup",
        "optimizer",
        "provider_execution",
        "output_guardrail",
        "cache_store",
        "usage_log",
    ]
    provider = next(r for r in client.records if r["create"]["name"] == "provider_execution")
    assert provider["updates"][0]["usage_details"] == {"input": 11, "output": 17, "total": 28}
    assert provider["create"]["metadata"]["latency_ms"] == 321


def test_sensitive_prompt_never_reaches_trace_payload():
    client = FakeLangfuseClient()
    exporter = LangfuseTraceExporter(config=enabled_config(), client=client)
    secret = "My API key is sk-secret-value"
    req = UsageLogRequest(
        request_id="r-sensitive",
        prompt=secret,
        guardrail_status="passed_with_redaction",
        cache_status="miss",
        graph_path="local_only_path",
        privacy_enforced=True,
        prompt_redaction_applied=True,
        provider="ollama",
        model="llama3.1:latest",
        requested_tier="local",
        executed_tier="local",
        actual_total_tokens=10,
        actual_execution_attempt_count=1,
        output_guardrail_status="passed",
    )

    result = exporter.export_usage(req)
    serialized = json.dumps(client.records)

    assert result.exported is True
    assert secret not in serialized
    assert "sk-secret-value" not in serialized
    assert "prompt_fingerprint" in serialized
    root_metadata = client.records[0]["create"]["metadata"]
    assert root_metadata["privacy_enforced"] is True
    assert root_metadata["prompt_redaction_applied"] is True
    assert root_metadata["raw_prompt_exported"] is False


def test_trace_url_uses_browser_facing_host():
    client = FakeLangfuseClient(trace_base_url="http://langfuse-web:3000")
    config = ObservabilityConfig(
        requested_enabled=True,
        public_key="lf_pk_test",
        secret_key="lf_sk_test",
        base_url="http://langfuse-web:3000",
        public_url="http://localhost:3000",
        environment="test",
        release="test-release",
        flush_on_export=True,
    )
    exporter = LangfuseTraceExporter(config=config, client=client)

    result = exporter.export_usage(UsageLogRequest(request_id="r-public-url"))

    assert result.trace_url == "http://localhost:3000/trace/" + "a" * 32


def test_cache_hit_skips_optimizer_and_provider_spans():
    client = FakeLangfuseClient()
    exporter = LangfuseTraceExporter(config=enabled_config(), client=client)
    req = UsageLogRequest(
        request_id="r-cache",
        prompt="cached question",
        cache_status="hit",
        cache_confidence=0.94,
        provider="not called - semantic cache",
        requested_tier="cache",
        executed_tier="cache",
        savings_source="semantic_cache",
        output_guardrail_status="passed",
    )

    result = exporter.export_usage(req)
    names = observation_names(client)

    assert result.exported is True
    assert "semantic_cache_lookup" in names
    assert "optimizer" not in names
    assert "provider_execution" not in names
    assert "cache_store" not in names


def test_disabled_exporter_is_fail_open():
    client = FakeLangfuseClient()
    config = ObservabilityConfig(
        requested_enabled=False,
        public_key="",
        secret_key="",
        base_url="http://langfuse.local",
        environment="test",
        release="test",
        flush_on_export=True,
    )
    exporter = LangfuseTraceExporter(config=config, client=client)

    result = exporter.export_usage(UsageLogRequest(request_id="r-disabled"))

    assert result.tracing_enabled is False
    assert result.exported is False
    assert result.skipped_reason == "tracing_disabled"
    assert client.records == []


def test_usage_log_handler_returns_successful_trace_fields(monkeypatch):
    class SuccessfulExporter:
        config = enabled_config()

        @staticmethod
        def export_usage(_req):
            return TraceExportResult(
                tracing_enabled=True,
                attempted=True,
                exported=True,
                trace_id="a" * 32,
                trace_url="http://langfuse.local/trace/" + "a" * 32,
            )

    monkeypatch.setattr(
        optimizer_main,
        "log_usage",
        lambda req: UsageLogResponse(logged=True, request_id=req.request_id),
    )
    monkeypatch.setattr(optimizer_main, "get_trace_exporter", lambda: SuccessfulExporter())
    monkeypatch.setattr(optimizer_main, "get_export_record", lambda _request_id: None)
    monkeypatch.setattr(optimizer_main, "record_export_attempt", lambda *args, **kwargs: None)

    response = optimizer_main.usage_log(UsageLogRequest(request_id="r-handler"))

    assert response.logged is True
    assert response.trace_exported is True
    assert response.tracing_enabled is True
    assert response.trace_id == "a" * 32
    assert response.trace_error is None


def test_export_status_retries_then_becomes_idempotent():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        init_db(path)
        from usage.repository import log_usage

        log_usage(UsageLogRequest(request_id="r-retry"), db_path=path)
        failed = record_export_attempt(
            "r-retry",
            trace_id="a" * 32,
            trace_url=None,
            exported=False,
            error="connection refused",
            db_path=path,
        )
        assert failed.exported is False
        assert failed.attempt_count == 1

        succeeded = record_export_attempt(
            "r-retry",
            trace_id="a" * 32,
            trace_url="http://langfuse.local/trace/" + "a" * 32,
            exported=True,
            error=None,
            db_path=path,
        )
        assert succeeded.exported is True
        assert succeeded.attempt_count == 2
        assert succeeded.last_error is None
        assert get_export_record("r-retry", db_path=path) == succeeded
        assert get_export_counts(db_path=path) == {"exported": 1, "failed": 0, "pending": 0}
    finally:
        os.unlink(path)
