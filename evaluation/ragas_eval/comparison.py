"""Derived MomiHelm evaluation metrics and baseline-vs-optimized comparison.

quality_preservation_ratio is a MomiHelm PROJECT-LEVEL derived metric, NOT a
built-in Ragas metric. All functions here are pure for straightforward testing.
"""
from __future__ import annotations

from typing import Optional

from .config import QualityWeights
from .metrics import M_SEMANTIC, M_RELEVANCY, M_FACTUAL, M_RUBRIC

COMPOSITE_METRICS = [M_SEMANTIC, M_RELEVANCY, M_FACTUAL, M_RUBRIC]


def composite_quality(
    scores: dict[str, Optional[float]], weights: QualityWeights
) -> dict[str, object]:
    """Weighted composite quality in [0,1] over AVAILABLE metrics only.

    Missing/failed metrics (value is None) are excluded and the remaining
    weights are renormalized. A failed metric is never substituted with 0.
    """
    wmap = weights.as_map()
    used: dict[str, float] = {}
    missing: list[str] = []
    for m in COMPOSITE_METRICS:
        v = scores.get(m)
        if v is None:
            missing.append(m)
        else:
            used[m] = float(v)

    total_w = sum(wmap[m] for m in used)
    if not used or total_w <= 0:
        return {"composite": None, "used_metrics": [], "missing_metrics": missing}

    composite = sum(used[m] * (wmap[m] / total_w) for m in used)
    return {
        "composite": round(composite, 6),
        "used_metrics": sorted(used.keys()),
        "missing_metrics": missing,
    }


def mean(values: list[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 6)


def quality_preservation_ratio(
    baseline_mean: Optional[float], optimized_mean: Optional[float]
) -> Optional[float]:
    """optimized_mean / baseline_mean (MomiHelm derived metric)."""
    if baseline_mean is None or optimized_mean is None or baseline_mean <= 0:
        return None
    return round(optimized_mean / baseline_mean, 6)


def evaluate_quality_gate(
    ratio: Optional[float],
    gate_ratio: float,
    quality_critical_composites: list[Optional[float]],
    quality_critical_min: float,
    behavioral_pass_rate: Optional[float],
) -> dict[str, object]:
    """Compose the overall pass/fail decision with explicit sub-results."""
    reasons: list[str] = []

    ratio_ok = ratio is not None and ratio >= gate_ratio
    if ratio is None:
        reasons.append("quality_preservation_ratio unavailable")
    elif not ratio_ok:
        reasons.append(f"quality_preservation_ratio {ratio} < gate {gate_ratio}")

    crit_vals = [c for c in quality_critical_composites if c is not None]
    crit_ok = all(c >= quality_critical_min for c in crit_vals) if crit_vals else True
    if not crit_ok:
        reasons.append(
            f"a quality-critical case scored below {quality_critical_min}"
        )

    behavioral_ok = behavioral_pass_rate is None or behavioral_pass_rate >= 1.0
    if behavioral_pass_rate is not None and not behavioral_ok:
        reasons.append(f"behavioral pass rate {behavioral_pass_rate} < 1.0")

    passed = bool(ratio_ok and crit_ok and behavioral_ok)
    return {
        "passed": passed,
        "ratio_ok": ratio_ok,
        "quality_critical_ok": crit_ok,
        "behavioral_ok": behavioral_ok,
        "reasons": reasons,
    }


# --------------------------------------------------------------------------- #
# Efficiency deltas
# --------------------------------------------------------------------------- #
def _pct(delta: Optional[float], base: Optional[float]) -> Optional[float]:
    if delta is None or base is None or base == 0:
        return None
    return round((delta / base) * 100.0, 4)


def token_deltas(baseline: dict, tokenwise: dict) -> dict[str, Optional[float]]:
    b_in, t_in = baseline.get("input_tokens"), tokenwise.get("input_tokens")
    b_out, t_out = baseline.get("output_tokens"), tokenwise.get("output_tokens")
    b_tot, t_tot = baseline.get("total_tokens"), tokenwise.get("total_tokens")

    def d(a, b):
        return (a - b) if (a is not None and b is not None) else None

    total_delta = d(t_tot, b_tot)
    return {
        "input_token_delta": d(t_in, b_in),
        "output_token_delta": d(t_out, b_out),
        "total_token_delta": total_delta,
        "token_reduction_percentage": _pct(-total_delta if total_delta is not None else None, b_tot),
    }


def latency_deltas(baseline: dict, tokenwise: dict) -> dict[str, Optional[float]]:
    b, t = baseline.get("latency_ms"), tokenwise.get("latency_ms")
    delta = (t - b) if (b is not None and t is not None) else None
    return {
        "latency_delta_ms": round(delta, 2) if delta is not None else None,
        "latency_change_percentage": _pct(delta, b),
    }


def cost_deltas(baseline: dict, tokenwise: dict) -> dict[str, Optional[float]]:
    b_model = baseline.get("modeled_baseline_cost")
    t_model = (
        tokenwise.get("modeled_optimized_cost")
        if tokenwise.get("modeled_optimized_cost") is not None
        else tokenwise.get("modeled_baseline_cost")
    )
    delta = (t_model - b_model) if (b_model is not None and t_model is not None) else None
    return {
        "actual_provider_api_cost_baseline": baseline.get("actual_cost"),
        "actual_provider_api_cost_tokenwise": tokenwise.get("actual_cost"),
        "modeled_baseline_cost": b_model,
        "modeled_optimized_cost": t_model,
        "modeled_cost_delta": round(delta, 6) if delta is not None else None,
        "modeled_savings_percentage": _pct(-delta if delta is not None else None, b_model),
    }
