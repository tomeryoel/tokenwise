"""Ragas API compatibility + metric result extraction tests
(points 1, 12, 13, 14, 15, 32, 34)."""
from pathlib import Path

import pytest

from evaluation.ragas_eval.config import EvalConfig
from evaluation.ragas_eval.metrics import (
    MetricEngine, assert_ragas_api, _result_to_score,
    M_SEMANTIC, M_RELEVANCY, M_FACTUAL, M_RUBRIC,
)
from .conftest import FakeMetricResult


def test_ragas_api_is_collections_generation():
    ver = assert_ragas_api()
    major, minor = ver.split(".")[:2]
    assert (int(major), int(minor)) >= (0, 4)


def test_deprecated_evaluate_api_not_imported_in_package():
    """Point 32: our package must use the collections/experiment API, not the
    deprecated ``from ragas import evaluate`` batch API. Uses AST so docstring
    mentions of the deprecated name do not count as usage."""
    import ast

    pkg_dir = Path(__file__).resolve().parents[1]
    offenders = []
    for py in pkg_dir.glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=py.name)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "ragas":
                imported = {a.name for a in node.names}
                if imported & {"evaluate", "aevaluate"}:
                    offenders.append(py.name)
    assert offenders == []


def test_semantic_result_extraction():
    s = _result_to_score(M_SEMANTIC, "baseline", FakeMetricResult(0.73, "close"))
    assert s.status == "ok" and s.value == 0.73 and s.reason == "close"


def test_llm_metric_result_extraction():
    s = _result_to_score(M_FACTUAL, "tokenwise", FakeMetricResult(0.5))
    assert s.status == "ok" and s.value == 0.5


def test_non_numeric_metric_is_error_not_fake_zero():
    """Point 34: a failed/garbage metric must NOT become a 0.0 score."""
    s = _result_to_score(M_RELEVANCY, "baseline", FakeMetricResult("not-a-number"))
    assert s.status == "error"
    assert s.value is None


async def test_rubric_extraction_and_normalization():
    """Point 14: rubric 1-5 raw score normalized to 0-1, raw kept in reason."""
    eng = MetricEngine(EvalConfig())

    class FakeRubric:
        async def ascore(self, **kwargs):
            return FakeMetricResult(5.0, "great")

    eng._rubric = FakeRubric()
    s = await eng.score_rubric("tokenwise", "q", "ref", "resp")
    assert s.status == "ok"
    assert s.value == 1.0  # (5-1)/(5-1)
    assert "raw_1_5=5.0" in s.reason


async def test_metric_failure_recorded_without_crash():
    """Point 15: a raising metric is captured as status=error, run continues."""
    eng = MetricEngine(EvalConfig())

    class Boom:
        async def ascore(self, **kwargs):
            raise RuntimeError("judge exploded")

    eng._semantic = Boom()
    s = await eng.score_semantic("baseline", "ref", "resp")
    assert s.status == "error"
    assert "judge exploded" in s.error


async def test_missing_inputs_are_not_applicable():
    eng = MetricEngine(EvalConfig())
    s = await eng.score_semantic("baseline", "", "resp")
    assert s.status == "not_applicable"
