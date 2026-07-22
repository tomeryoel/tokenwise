"""Focused tests for targeted case/metric filtering (grounding remediation)."""

from __future__ import annotations

import pytest

from evaluation.ragas_eval.dataset import filter_by_case_id, load_cases, DatasetValidationError
from evaluation.ragas_eval.experiments import (
    _metric_plan,
    parse_metric_filter,
    M_SEMANTIC,
    M_RELEVANCY,
    M_FACTUAL,
    M_RUBRIC,
)
from evaluation.ragas_eval.schemas import EvalCase


def _case(**kwargs) -> EvalCase:
    base = dict(
        case_id="tw-architecture-001",
        category="tokenwise_architecture",
        kind="answer_quality",
        user_input="Explain how MomiHelm chooses between a local model and an external model.",
        reference="Rule-based through LangGraph.",
        expected_behavior="answer",
        run_semantic_similarity=True,
        run_response_relevancy=True,
        run_factual_correctness=True,
        run_custom_rubric=True,
        quality_critical=True,
        smoke=True,
    )
    base.update(kwargs)
    return EvalCase(**base)


def test_filter_by_case_id_selects_exactly_one():
    cases, _ = load_cases()
    selected = filter_by_case_id(cases, "tw-architecture-001")
    assert len(selected) == 1
    assert selected[0].case_id == "tw-architecture-001"


def test_unknown_case_id_rejected():
    cases, _ = load_cases()
    with pytest.raises(DatasetValidationError, match="unknown case_id"):
        filter_by_case_id(cases, "does-not-exist-999")


def test_parse_metric_filter_aliases():
    filt = parse_metric_filter("semantic_similarity,tokenwise_grounding_rubric")
    assert filt == {M_SEMANTIC, M_RUBRIC}


def test_parse_metric_filter_rejects_unknown():
    with pytest.raises(ValueError, match="unknown metric"):
        parse_metric_filter("semantic_similarity,not_a_metric")


def test_metric_filter_excludes_factual_correctness():
    case = _case()
    plan = _metric_plan(
        case, "full", metric_filter={M_SEMANTIC, M_RUBRIC}
    )
    assert plan[M_SEMANTIC] is True
    assert plan[M_RUBRIC] is True
    assert plan[M_FACTUAL] is False
    assert plan[M_RELEVANCY] is False


def test_missing_metrics_stay_none_not_fake_zero():
    # Score extraction contract: failed/missing metrics must not become 0.0.
    from evaluation.ragas_eval.schemas import MetricScore
    from evaluation.ragas_eval.comparison import composite_quality
    from evaluation.ragas_eval.config import QualityWeights

    scores = {
        M_SEMANTIC: 0.8,
        M_RELEVANCY: None,  # missing — not a fake zero
        M_FACTUAL: None,
        M_RUBRIC: 0.9,
    }
    result = composite_quality(scores, QualityWeights())
    assert result["composite"] is not None
    assert result["composite"] > 0.0
    # Renormalized over available metrics only
    assert M_RELEVANCY not in result["used_metrics"]
    assert M_FACTUAL not in result["used_metrics"]

    err = MetricScore(M_FACTUAL, "baseline", status="error", error="TimeoutError")
    assert err.value is None
    assert err.status == "error"
