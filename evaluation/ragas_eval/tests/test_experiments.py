"""Behavioral assertion + git metadata tests (points 23, 24, 25, 33)."""
from evaluation.ragas_eval.config import EvalConfig
from evaluation.ragas_eval.experiments import ExperimentRunner, git_commit, _is_external
from evaluation.ragas_eval.schemas import EvalCase, BEHAVIORAL
from evaluation.ragas_eval.clients import safe_parse_receipt
from evaluation.ragas_eval.schemas import VariantExecution


def _runner():
    cfg = EvalConfig()
    cfg.run_id = "run-x"
    cfg.department = "ragas-eval-run-x"
    return ExperimentRunner(cfg)


def _tw(receipt):
    return VariantExecution(variant="tokenwise", answer="a",
                            receipt=safe_parse_receipt(receipt))


async def test_guardrail_block_behavioral_pass():
    r = _runner()
    r.tokenwise.run = lambda *a, **k: _tw(
        {"guardrail_status": "blocked", "provider": "not called — guardrail block",
         "detected_risk_type": "secret", "reason": "secret_detected"})
    case = EvalCase(case_id="beh-secret", category="behavioral_guardrail", kind=BEHAVIORAL,
                    user_input="api_key=sk-x", expect_blocked=True, expect_no_external=True)
    out = await r._run_behavioral(case)
    assert out["passed"] is True
    assert out["observed"]["guardrail_status"] == "blocked"


async def test_guardrail_block_fails_when_not_blocked():
    r = _runner()
    r.tokenwise.run = lambda *a, **k: _tw(
        {"guardrail_status": "passed", "provider": "openai"})
    case = EvalCase(case_id="beh-secret", category="behavioral_guardrail", kind=BEHAVIORAL,
                    user_input="x", expect_blocked=True, expect_no_external=True)
    out = await r._run_behavioral(case)
    assert out["passed"] is False
    assert "expected block" in out["detail"] or "external provider" in out["detail"]


async def test_pii_local_only_behavioral_pass():
    r = _runner()
    r.tokenwise.run = lambda *a, **k: _tw(
        {"guardrail_status": "passed_with_redaction", "provider": "ollama",
         "privacy_enforced": True, "prompt_redaction_applied": True,
         "executed_tier": "local"})
    case = EvalCase(case_id="beh-pii", category="behavioral_privacy", kind=BEHAVIORAL,
                    user_input="email evaluation.user@example.invalid",
                    expect_redaction=True, expect_local_only=True, expect_no_external=True)
    out = await r._run_behavioral(case)
    assert out["passed"] is True


async def test_cache_repeat_miss_then_hit_pass():
    r = _runner()
    seq = [
        _tw({"cache_status": "miss", "provider": "ollama", "selected_tier": "local"}),
        _tw({"cache_status": "hit", "provider": "not called — semantic cache",
             "selected_tier": "cache"}),
    ]
    calls = {"n": 0}

    def fake_run(*a, **k):
        out = seq[calls["n"]]
        calls["n"] += 1
        return out

    r.tokenwise.run = fake_run
    case = EvalCase(case_id="beh-cache", category="behavioral_cache", kind=BEHAVIORAL,
                    user_input="how does tokenwise save cost?", expect_cache_hit_on_repeat=True)
    out = await r._run_behavioral(case)
    assert out["passed"] is True
    assert out["observed"]["second_cache_status"] == "hit"


async def test_cache_repeat_fails_without_hit():
    r = _runner()
    r.tokenwise.run = lambda *a, **k: _tw({"cache_status": "miss", "provider": "ollama"})
    case = EvalCase(case_id="beh-cache", category="behavioral_cache", kind=BEHAVIORAL,
                    user_input="q", expect_cache_hit_on_repeat=True)
    out = await r._run_behavioral(case)
    assert out["passed"] is False


def test_git_commit_metadata_captured():
    gc = git_commit()
    assert set(gc.keys()) == {"commit", "short_commit", "dirty"}
    # inside this repo the commit hash is available
    assert gc["commit"] is None or len(gc["commit"]) >= 7


def test_is_external_detection():
    assert _is_external("openai") is True
    assert _is_external("ollama") is False
    assert _is_external("not called — semantic cache") is False
