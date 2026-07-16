"""Artifact generation + secret-scrubbing tests (points 26, 27, 28, 29, 31)."""
import csv
import os

from evaluation.ragas_eval.reporting import (
    scrub_secrets, build_markdown_report, write_artifacts, _score_row,
)
from evaluation.ragas_eval.metrics import M_SEMANTIC, M_RELEVANCY, M_FACTUAL, M_RUBRIC


def _mk(value, status="ok", reason=None):
    return {"value": value, "status": status, "reason": reason, "error": None}


def _case_result():
    return {
        "case_id": "tw-architecture-001",
        "category": "tokenwise_architecture",
        "kind": "answer_quality",
        "quality_critical": True,
        "user_input": "Explain routing.",
        "baseline": {"provider": "ollama", "model": "llama3.1:latest", "answer": "base",
                     "input_tokens": 10, "output_tokens": 20, "total_tokens": 30,
                     "latency_ms": 900, "actual_cost": 0.0, "modeled_baseline_cost": 0.001,
                     "modeled_optimized_cost": None, "error": None},
        "tokenwise": {"provider": "ollama", "model": "llama3.1:latest", "answer": "opt",
                      "input_tokens": 8, "output_tokens": 12, "total_tokens": 20,
                      "latency_ms": 1200, "actual_cost": 0.0, "modeled_baseline_cost": 0.001,
                      "modeled_optimized_cost": 0.0006, "error": None},
        "baseline_scores": {M_SEMANTIC: _mk(0.8), M_RUBRIC: _mk(0.75)},
        "tokenwise_scores": {M_SEMANTIC: _mk(0.82), M_RUBRIC: _mk(0.8)},
        "baseline_composite": {"composite": 0.78, "used_metrics": [M_SEMANTIC, M_RUBRIC],
                               "missing_metrics": []},
        "tokenwise_composite": {"composite": 0.81, "used_metrics": [M_SEMANTIC, M_RUBRIC],
                                "missing_metrics": []},
        "token_deltas": {"total_token_delta": -10, "token_reduction_percentage": 33.33},
        "latency_deltas": {"latency_delta_ms": 300.0, "latency_change_percentage": 33.33},
        "cost_deltas": {"modeled_cost_delta": -0.0004, "modeled_savings_percentage": 40.0},
    }


def _result():
    return {
        "metadata": {"run_id": "run-x", "ragas_version": "0.4.3",
                     "ragas_api_style": "experiment+collections (0.4.x)",
                     "judge_provider": "ollama", "judge_model": "llama3.1:latest",
                     "embedding_model": "all-MiniLM-L6-v2", "mode": "smoke",
                     "policy_mode": "balanced", "quality_gate_ratio": 0.9,
                     "generator_calls": 4, "judge_calls": 2, "embedding_calls": 4,
                     "duration_seconds": 12.0, "tokenwise_git_commit": "abc123",
                     "dataset_fingerprint": "deadbeef", "evaluation_department": "ragas-eval-x"},
        "aggregates": {"baseline_metric_means": {M_SEMANTIC: 0.8, M_RUBRIC: 0.75},
                       "tokenwise_metric_means": {M_SEMANTIC: 0.82, M_RUBRIC: 0.8},
                       "metric_deltas": {M_SEMANTIC: 0.02, M_RUBRIC: 0.05},
                       "baseline_mean_composite": 0.78, "tokenwise_mean_composite": 0.81,
                       "quality_preservation_ratio": 1.038,
                       "quality_gate": {"passed": True, "reasons": []},
                       "behavioral_pass_rate": 1.0, "behavioral_count": 2,
                       "roi_status": "operating_cost_not_modeled", "roi_percentage": None,
                       "mean_total_token_delta": -10, "mean_latency_delta_ms": 300,
                       "mean_modeled_cost_delta": -0.0004},
        "ragas_experiment_name": "run-x-smoke",
        "case_results": [_case_result()],
        "behavioral_results": [{"case_id": "beh-1", "category": "behavioral_guardrail",
                                "kind": "behavioral", "expected_behavior": "block",
                                "passed": True, "observed": {}, "detail": "ok"}],
        "errors": [],
    }


def test_scrub_secrets_redacts_nested():
    data = {"answer": "my key is sk-abcd1234efgh5678",
            "list": ["api_key=supersecretvalue", "safe text"],
            "nested": {"token": "ghp_ABCDEFGHIJKLMNOPQRSTUV12345"}}
    out = scrub_secrets(data)
    flat = str(out)
    assert "sk-abcd1234efgh5678" not in flat
    assert "supersecretvalue" not in flat
    assert "ghp_ABCDEFGHIJKLMNOPQRSTUV12345" not in flat
    assert "safe text" in flat


def test_no_environment_keys_in_serialized_errors(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-superenvsecret1234567890")
    errs = [{"case_id": "c1", "error": "OPENAI_API_KEY=sk-superenvsecret1234567890 leaked"}]
    scrubbed = scrub_secrets(errs)
    assert "sk-superenvsecret1234567890" not in str(scrubbed)


def test_score_row_keeps_baseline_and_tokenwise_separate():
    row = _score_row(_case_result())
    assert row[f"baseline_{M_SEMANTIC}"] == 0.8
    assert row[f"tokenwise_{M_SEMANTIC}"] == 0.82
    assert row[f"{M_SEMANTIC}_delta"] == round(0.82 - 0.8, 6)
    # separate columns, never overwritten
    assert row["baseline_composite"] == 0.78
    assert row["tokenwise_composite"] == 0.81


def test_markdown_report_has_key_sections():
    md = build_markdown_report({"dataset_version": "1.0.0"}, {"dataset_version": "1.0.0"}, _result())
    for heading in ["## Objective", "## Quality metrics", "quality_preservation_ratio",
                    "## Behavioral system results", "## Limitations",
                    "## Evidence-based conclusion"]:
        assert heading in md


def test_write_artifacts_creates_all_files(tmp_path):
    written = write_artifacts(tmp_path, {"cfg": 1}, {"dataset_version": "1.0.0"}, _result())
    for key in ["config", "dataset_snapshot", "baseline_results", "tokenwise_results",
                "ragas_scores", "comparison", "summary", "report", "errors"]:
        assert key in written
        assert os.path.exists(written[key])
    # errors.json is always present (empty list on a clean run)
    import json
    with open(written["errors"], encoding="utf-8") as fh:
        assert json.load(fh) == []
    # CSV is real, parseable and has separate baseline/tokenwise columns
    with open(written["ragas_scores"], newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows and f"baseline_{M_SEMANTIC}" in rows[0] and f"tokenwise_{M_SEMANTIC}" in rows[0]
