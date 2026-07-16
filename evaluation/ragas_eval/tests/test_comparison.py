"""Derived-metric and comparison tests (points 16-22)."""
from evaluation.ragas_eval.comparison import (
    composite_quality, quality_preservation_ratio, evaluate_quality_gate,
    token_deltas, latency_deltas, cost_deltas, mean,
)
from evaluation.ragas_eval.config import QualityWeights
from evaluation.ragas_eval.metrics import M_SEMANTIC, M_RELEVANCY, M_FACTUAL, M_RUBRIC


def test_composite_quality_full_weights():
    w = QualityWeights()
    scores = {M_SEMANTIC: 1.0, M_RELEVANCY: 1.0, M_FACTUAL: 1.0, M_RUBRIC: 1.0}
    res = composite_quality(scores, w)
    assert res["composite"] == 1.0
    assert res["missing_metrics"] == []


def test_weight_renormalization_excludes_missing():
    w = QualityWeights()
    # only semantic + factual present -> weights renormalize over 0.35 + 0.25
    scores = {M_SEMANTIC: 0.8, M_RELEVANCY: None, M_FACTUAL: 0.4, M_RUBRIC: None}
    res = composite_quality(scores, w)
    expected = (0.8 * 0.35 + 0.4 * 0.25) / (0.35 + 0.25)
    assert abs(res["composite"] - round(expected, 6)) < 1e-6
    assert set(res["missing_metrics"]) == {M_RELEVANCY, M_RUBRIC}


def test_failed_metric_is_not_a_fake_zero():
    w = QualityWeights()
    only = composite_quality({M_SEMANTIC: 0.9}, w)
    with_zero = composite_quality({M_SEMANTIC: 0.9, M_FACTUAL: 0.0}, w)
    # excluding the missing metric must NOT behave like substituting 0.0
    assert only["composite"] == 0.9
    assert with_zero["composite"] != only["composite"]


def test_all_missing_returns_none():
    res = composite_quality({M_SEMANTIC: None}, QualityWeights())
    assert res["composite"] is None


def test_quality_preservation_ratio():
    assert quality_preservation_ratio(0.8, 0.76) == 0.95
    assert quality_preservation_ratio(0.0, 0.5) is None
    assert quality_preservation_ratio(None, 0.5) is None


def test_quality_gate_pass_and_fail():
    ok = evaluate_quality_gate(0.95, 0.90, [0.8, 0.7], 0.6, 1.0)
    assert ok["passed"] is True
    bad_ratio = evaluate_quality_gate(0.5, 0.90, [0.8], 0.6, 1.0)
    assert bad_ratio["passed"] is False
    bad_crit = evaluate_quality_gate(0.95, 0.90, [0.5], 0.6, 1.0)
    assert bad_crit["passed"] is False and not bad_crit["quality_critical_ok"]
    bad_beh = evaluate_quality_gate(0.95, 0.90, [0.8], 0.6, 0.8)
    assert bad_beh["passed"] is False and not bad_beh["behavioral_ok"]


def test_token_delta():
    b = {"input_tokens": 100, "output_tokens": 200, "total_tokens": 300}
    t = {"input_tokens": 80, "output_tokens": 120, "total_tokens": 200}
    d = token_deltas(b, t)
    assert d["total_token_delta"] == -100
    assert d["token_reduction_percentage"] == round((100 / 300) * 100, 4)


def test_latency_delta():
    d = latency_deltas({"latency_ms": 1000}, {"latency_ms": 1500})
    assert d["latency_delta_ms"] == 500.0
    assert d["latency_change_percentage"] == 50.0


def test_cost_delta():
    b = {"modeled_baseline_cost": 0.010, "actual_cost": 0.0}
    t = {"modeled_optimized_cost": 0.004, "actual_cost": 0.0}
    d = cost_deltas(b, t)
    assert d["modeled_cost_delta"] == -0.006
    assert d["modeled_savings_percentage"] == 60.0


def test_mean_ignores_none():
    assert mean([1.0, None, 3.0]) == 2.0
    assert mean([None]) is None
