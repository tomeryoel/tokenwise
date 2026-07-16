"""Experiment orchestration with real Ragas experiment tracking.

Generation + judging run sequentially (bounded concurrency) to protect the local
Ollama judge. Scored rows are then recorded through the genuine Ragas
``@experiment()`` / ``Dataset.arun()`` mechanism so this is a tracked experiment,
not an untracked loop.
"""
from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

from .clients import BaselineClient, TokenWiseClient, check_url, check_ollama
from .comparison import (
    composite_quality, cost_deltas, latency_deltas, token_deltas,
    mean, quality_preservation_ratio, evaluate_quality_gate,
)
from .config import EvalConfig
from .metrics import (
    MetricEngine, assert_ragas_api, ragas_version,
    M_SEMANTIC, M_RELEVANCY, M_FACTUAL, M_RUBRIC,
)
from .schemas import EvalCase

EXTERNAL_PROVIDERS = {"openai", "anthropic", "gemini", "google"}


def git_commit() -> dict[str, Any]:
    def _run(args: list[str]) -> Optional[str]:
        try:
            out = subprocess.run(["git", *args], capture_output=True, text=True, timeout=10)
            return out.stdout.strip() if out.returncode == 0 else None
        except Exception:  # noqa: BLE001
            return None

    head = _run(["rev-parse", "HEAD"])
    dirty = _run(["status", "--porcelain"])
    return {
        "commit": head,
        "short_commit": head[:10] if head else None,
        "dirty": bool(dirty) if dirty is not None else None,
    }


@dataclass
class ExperimentMetadata:
    run_id: str
    mode: str
    dataset_version: str
    dataset_fingerprint: str
    ragas_version: str
    ragas_api_style: str
    judge_provider: str
    judge_model: str
    embedding_model: str
    baseline_provider: str
    baseline_model: str
    tokenwise_git_commit: Optional[str]
    tokenwise_git_dirty: Optional[bool]
    policy_mode: str
    evaluation_department: str
    metric_weights: dict[str, float]
    quality_gate_ratio: float
    quality_critical_min: float
    started_at: str = ""
    ended_at: str = ""
    duration_seconds: Optional[float] = None
    generator_calls: int = 0
    judge_calls: int = 0
    embedding_calls: int = 0
    success_count: int = 0
    error_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _metric_plan(case: EvalCase, mode: str) -> dict[str, bool]:
    """Which metrics to run for a case. Smoke mode trims slow judge metrics."""
    if mode == "smoke":
        return {
            M_SEMANTIC: case.run_semantic_similarity,
            M_RELEVANCY: False,
            M_FACTUAL: False,
            M_RUBRIC: case.run_custom_rubric and case.quality_critical,
        }
    return {
        M_SEMANTIC: case.run_semantic_similarity,
        M_RELEVANCY: case.run_response_relevancy,
        M_FACTUAL: case.run_factual_correctness,
        M_RUBRIC: case.run_custom_rubric,
    }


def _is_external(provider: Optional[str]) -> bool:
    if not provider:
        return False
    p = provider.lower()
    return any(x in p for x in EXTERNAL_PROVIDERS)


class ExperimentRunner:
    def __init__(self, cfg: EvalConfig):
        self.cfg = cfg
        self.baseline = BaselineClient(cfg)
        self.tokenwise = TokenWiseClient(cfg)
        self.engine = MetricEngine(cfg)
        self.errors: list[dict[str, Any]] = []
        self.generator_calls = 0

    # -- health + warmup -----------------------------------------------------
    def health_check(self) -> dict[str, Any]:
        checks: dict[str, Any] = {}
        ok, msg = check_ollama(self.cfg)
        checks["ollama"] = {"ok": ok, "detail": msg}
        ok, msg = check_url(self.cfg.n8n_health_url)
        checks["n8n"] = {"ok": ok, "detail": msg}
        ok, msg = check_url(self.cfg.optimizer_health_url)
        checks["optimizer"] = {"ok": ok, "detail": msg}
        # embeddings init
        try:
            self.engine._build_embeddings()
            checks["embeddings"] = {"ok": True, "detail": self.cfg.embedding_model}
        except Exception as exc:  # noqa: BLE001
            checks["embeddings"] = {"ok": False, "detail": type(exc).__name__}
        checks["all_ok"] = all(v.get("ok") for k, v in checks.items() if isinstance(v, dict))
        return checks

    def warmup(self) -> None:
        """Prime the Ollama model so the first real calls are not cold."""
        try:
            self.baseline.generate("Reply with the single word: ready.")
        except Exception:  # noqa: BLE001
            pass

    # -- per-case ------------------------------------------------------------
    async def _score_variant(self, case: EvalCase, variant: str, answer: str,
                             plan: dict[str, bool]) -> dict[str, Any]:
        scores: dict[str, Any] = {}
        ref = case.reference or ""
        if plan.get(M_SEMANTIC):
            s = await self.engine.score_semantic(variant, ref, answer)
            scores[M_SEMANTIC] = s
            self._track_error(case, s)
        if plan.get(M_RELEVANCY):
            s = await self.engine.score_relevancy(variant, case.user_input, answer)
            scores[M_RELEVANCY] = s
            self._track_error(case, s)
        if plan.get(M_FACTUAL):
            s = await self.engine.score_factual(variant, ref, answer)
            scores[M_FACTUAL] = s
            self._track_error(case, s)
        if plan.get(M_RUBRIC):
            s = await self.engine.score_rubric(variant, case.user_input, ref, answer)
            scores[M_RUBRIC] = s
            self._track_error(case, s)
        return scores

    def _track_error(self, case: EvalCase, score) -> None:
        if score.status == "error":
            self.errors.append({
                "case_id": case.case_id, "variant": score.variant, "stage": "metric",
                "metric": score.metric, "error_type": "metric_error",
                "error": score.error, "retry": "no",
            })

    def _values(self, scores: dict[str, Any]) -> dict[str, Optional[float]]:
        return {m: (s.value if s.status == "ok" else None) for m, s in scores.items()}

    async def _run_answer_quality(self, case: EvalCase, mode: str) -> dict[str, Any]:
        plan = _metric_plan(case, mode)
        # 1) generate both variants (bypass vs real pipeline)
        print(f"  [gen] baseline {case.case_id}", flush=True)
        self.generator_calls += 1
        base_exec = self.baseline.generate(case.user_input)
        if base_exec.error:
            self.errors.append({"case_id": case.case_id, "variant": "baseline",
                                "stage": "generation", "metric": None,
                                "error_type": "baseline_generation", "error": base_exec.error,
                                "retry": "no"})
        print(f"  [gen] tokenwise {case.case_id}", flush=True)
        self.generator_calls += 1
        tw_exec = self.tokenwise.run(case.user_input, self.cfg.department, self.cfg.policy_mode)
        if tw_exec.error:
            self.errors.append({"case_id": case.case_id, "variant": "tokenwise",
                                "stage": "generation", "metric": None,
                                "error_type": "tokenwise_generation", "error": tw_exec.error,
                                "retry": "no"})

        # 2) score each variant separately (never overwrite one with the other)
        print(f"  [score] baseline {case.case_id} metrics={list(k for k,v in plan.items() if v)}", flush=True)
        base_scores = await self._score_variant(case, "baseline", base_exec.answer or "", plan)
        print(f"  [score] tokenwise {case.case_id}", flush=True)
        tw_scores = await self._score_variant(case, "tokenwise", tw_exec.answer or "", plan)

        base_comp = composite_quality(self._values(base_scores), self.cfg.weights)
        tw_comp = composite_quality(self._values(tw_scores), self.cfg.weights)

        return {
            "case_id": case.case_id,
            "category": case.category,
            "kind": case.kind,
            "quality_critical": case.quality_critical,
            "user_input": case.user_input,
            "baseline": base_exec.to_dict(),
            "tokenwise": tw_exec.to_dict(),
            "baseline_scores": {m: s.to_dict() for m, s in base_scores.items()},
            "tokenwise_scores": {m: s.to_dict() for m, s in tw_scores.items()},
            "baseline_composite": base_comp,
            "tokenwise_composite": tw_comp,
            "token_deltas": token_deltas(base_exec.to_dict(), tw_exec.to_dict()),
            "latency_deltas": latency_deltas(base_exec.to_dict(), tw_exec.to_dict()),
            "cost_deltas": cost_deltas(base_exec.to_dict(), tw_exec.to_dict()),
        }

    async def _run_behavioral(self, case: EvalCase) -> dict[str, Any]:
        observed: dict[str, Any] = {}
        passed = True
        detail: list[str] = []

        if case.expect_cache_hit_on_repeat:
            self.generator_calls += 1
            first = self.tokenwise.run(case.user_input, self.cfg.department, self.cfg.policy_mode)
            self.generator_calls += 1
            second = self.tokenwise.run(case.user_input, self.cfg.department, self.cfg.policy_mode)
            first_status = (first.receipt or {}).get("cache_status")
            second_status = (second.receipt or {}).get("cache_status")
            second_tier = (second.receipt or {}).get("selected_tier")
            second_provider = (second.receipt or {}).get("provider")
            observed = {
                "first_cache_status": first_status, "second_cache_status": second_status,
                "second_selected_tier": second_tier, "second_provider": second_provider,
                "first_provider": (first.receipt or {}).get("provider"),
            }
            miss_ok = first_status in ("miss", None)  # cold dept -> miss (None if field absent)
            hit_ok = second_status == "hit"
            skip_ok = second_tier == "cache" or (second_provider or "").startswith("not called")
            passed = bool(miss_ok and hit_ok and skip_ok)
            if not miss_ok:
                detail.append(f"first request not a miss (got {first_status})")
            if not hit_ok:
                detail.append(f"second request not a hit (got {second_status})")
            if not skip_ok:
                detail.append("second request did not skip provider execution")
            return self._behavioral_result(case, passed, observed, detail)

        self.generator_calls += 1
        exec_ = self.tokenwise.run(case.user_input, self.cfg.department, self.cfg.policy_mode)
        r = exec_.receipt or {}
        observed = {
            "guardrail_status": r.get("guardrail_status"),
            "provider": r.get("provider"),
            "executed_tier": r.get("executed_tier"),
            "privacy_enforced": r.get("privacy_enforced"),
            "prompt_redaction_applied": r.get("prompt_redaction_applied"),
            "detected_risk_type": r.get("detected_risk_type"),
            "cache_status": r.get("cache_status"),
            "reason": r.get("reason"),
            "answer_present": bool(exec_.answer),
        }

        if case.expect_blocked:
            blocked_ok = r.get("guardrail_status") == "blocked"
            if not blocked_ok:
                passed = False
                detail.append(f"expected block, guardrail_status={r.get('guardrail_status')}")
        if case.expect_redaction:
            red_ok = bool(r.get("prompt_redaction_applied")) or "redaction" in str(r.get("guardrail_status"))
            if not red_ok:
                passed = False
                detail.append("expected redaction not applied")
        if case.expect_local_only:
            local_ok = bool(r.get("privacy_enforced")) or (r.get("provider") == "ollama")
            if not local_ok:
                passed = False
                detail.append("expected local-only enforcement not observed")
        if case.expect_no_external:
            if _is_external(r.get("provider")):
                passed = False
                detail.append(f"external provider used: {r.get('provider')}")

        return self._behavioral_result(case, passed, observed, detail)

    def _behavioral_result(self, case: EvalCase, passed: bool, observed: dict,
                          detail: list[str]) -> dict[str, Any]:
        return {
            "case_id": case.case_id,
            "category": case.category,
            "kind": case.kind,
            "expected_behavior": case.expected_behavior,
            "passed": passed,
            "observed": observed,
            "detail": "; ".join(detail) if detail else "ok",
        }

    # -- main entrypoint -----------------------------------------------------
    async def run(self, cases: list[EvalCase], meta: dict[str, Any], mode: str) -> dict[str, Any]:
        assert_ragas_api()
        started = datetime.now(timezone.utc)

        answer_cases = [c for c in cases if c.is_answer_quality()]
        behavioral_cases = [c for c in cases if not c.is_answer_quality()]

        case_results: list[dict[str, Any]] = []
        for i, case in enumerate(answer_cases, 1):
            print(f"[case] ({i}/{len(answer_cases)}) answer_quality {case.case_id}", flush=True)
            try:
                case_results.append(await self._run_answer_quality(case, mode))
                print(f"[case] done answer_quality {case.case_id}", flush=True)
            except Exception as exc:  # noqa: BLE001
                self.errors.append({"case_id": case.case_id, "variant": "both",
                                    "stage": "case", "metric": None,
                                    "error_type": "case_failure", "error": _short(exc),
                                    "retry": "no"})
                print(f"[case] FAIL answer_quality {case.case_id}: {type(exc).__name__}", flush=True)

        behavioral_results: list[dict[str, Any]] = []
        for i, case in enumerate(behavioral_cases, 1):
            print(f"[case] ({i}/{len(behavioral_cases)}) behavioral {case.case_id}", flush=True)
            try:
                behavioral_results.append(await self._run_behavioral(case))
                print(f"[case] done behavioral {case.case_id}", flush=True)
            except Exception as exc:  # noqa: BLE001
                self.errors.append({"case_id": case.case_id, "variant": "tokenwise",
                                    "stage": "behavioral", "metric": None,
                                    "error_type": "behavioral_failure", "error": _short(exc),
                                    "retry": "no"})
                print(f"[case] FAIL behavioral {case.case_id}: {type(exc).__name__}", flush=True)

        # Record through the genuine Ragas experiment mechanism (tracking).
        ragas_experiment_name = await self._record_ragas_experiment(case_results, mode, meta)

        aggregates = self._aggregate(case_results, behavioral_results)
        ended = datetime.now(timezone.utc)

        gc = git_commit()
        metadata = ExperimentMetadata(
            run_id=self.cfg.run_id,
            mode=mode,
            dataset_version=meta.get("dataset_version", "unknown"),
            dataset_fingerprint=meta.get("fingerprint", ""),
            ragas_version=ragas_version(),
            ragas_api_style="experiment+collections (0.4.x)",
            judge_provider=self.cfg.judge_provider,
            judge_model=self.cfg.judge_model,
            embedding_model=self.cfg.embedding_model,
            baseline_provider=self.cfg.baseline_provider,
            baseline_model=self.cfg.baseline_model,
            tokenwise_git_commit=gc.get("commit"),
            tokenwise_git_dirty=gc.get("dirty"),
            policy_mode=self.cfg.policy_mode,
            evaluation_department=self.cfg.department,
            metric_weights=self.cfg.weights.as_map(),
            quality_gate_ratio=self.cfg.quality_gate_ratio,
            quality_critical_min=self.cfg.quality_critical_min,
            started_at=started.isoformat(),
            ended_at=ended.isoformat(),
            duration_seconds=round((ended - started).total_seconds(), 2),
            generator_calls=self.generator_calls,
            judge_calls=self.engine.judge_calls,
            embedding_calls=self.engine.embedding_calls,
            success_count=len(case_results) + len(behavioral_results),
            error_count=len(self.errors),
        )

        return {
            "metadata": metadata.to_dict(),
            "ragas_experiment_name": ragas_experiment_name,
            "case_results": case_results,
            "behavioral_results": behavioral_results,
            "aggregates": aggregates,
            "errors": self.errors,
        }

    async def _record_ragas_experiment(self, case_results: list[dict[str, Any]],
                                        mode: str, meta: dict[str, Any]) -> Optional[str]:
        """Drive the precomputed scored rows through ragas @experiment/Dataset.arun."""
        try:
            from ragas import Dataset, experiment
            from ragas.backends import InMemoryBackend

            index = {c["case_id"]: c for c in case_results}

            @experiment()
            async def score_row(row):
                cr = index.get(row["case_id"], {})
                tw = cr.get("tokenwise_composite", {}) or {}
                bl = cr.get("baseline_composite", {}) or {}
                return {
                    "case_id": row["case_id"],
                    "category": row.get("category"),
                    "baseline_composite": bl.get("composite"),
                    "tokenwise_composite": tw.get("composite"),
                    **_flat_scores(cr),
                }

            ds = Dataset(name=f"tokenwise-eval-{mode}", backend=InMemoryBackend())
            for c in case_results:
                ds.append({"case_id": c["case_id"], "category": c.get("category")})
            if len(ds) == 0:
                return None
            exp = await score_row.arun(ds, name=f"{self.cfg.run_id}-{mode}",
                                       backend=InMemoryBackend())
            return getattr(exp, "name", None)
        except Exception as exc:  # noqa: BLE001
            self.errors.append({"case_id": None, "variant": None, "stage": "ragas_experiment",
                                "metric": None, "error_type": "experiment_tracking",
                                "error": _short(exc), "retry": "no"})
            return None

    def _aggregate(self, case_results: list[dict[str, Any]],
                  behavioral_results: list[dict[str, Any]]) -> dict[str, Any]:
        per_metric_baseline: dict[str, list[float]] = {M_SEMANTIC: [], M_RELEVANCY: [],
                                                       M_FACTUAL: [], M_RUBRIC: []}
        per_metric_tokenwise: dict[str, list[float]] = {M_SEMANTIC: [], M_RELEVANCY: [],
                                                        M_FACTUAL: [], M_RUBRIC: []}
        base_composites: list[float] = []
        tw_composites: list[float] = []
        crit_tw_composites: list[Optional[float]] = []

        for cr in case_results:
            for m, s in cr.get("baseline_scores", {}).items():
                if s.get("status") == "ok" and s.get("value") is not None:
                    per_metric_baseline[m].append(s["value"])
            for m, s in cr.get("tokenwise_scores", {}).items():
                if s.get("status") == "ok" and s.get("value") is not None:
                    per_metric_tokenwise[m].append(s["value"])
            bc = (cr.get("baseline_composite") or {}).get("composite")
            tc = (cr.get("tokenwise_composite") or {}).get("composite")
            if bc is not None:
                base_composites.append(bc)
            if tc is not None:
                tw_composites.append(tc)
            if cr.get("quality_critical"):
                crit_tw_composites.append(tc)

        baseline_means = {m: mean(v) for m, v in per_metric_baseline.items()}
        tokenwise_means = {m: mean(v) for m, v in per_metric_tokenwise.items()}
        metric_deltas = {
            m: (round(tokenwise_means[m] - baseline_means[m], 6)
                if baseline_means[m] is not None and tokenwise_means[m] is not None else None)
            for m in per_metric_baseline
        }

        base_mean_comp = mean(base_composites)
        tw_mean_comp = mean(tw_composites)
        qpr = quality_preservation_ratio(base_mean_comp, tw_mean_comp)

        behavioral_pass = [b["passed"] for b in behavioral_results]
        behavioral_pass_rate = (round(sum(behavioral_pass) / len(behavioral_pass), 4)
                                if behavioral_pass else None)

        gate = evaluate_quality_gate(
            qpr, self.cfg.quality_gate_ratio, crit_tw_composites,
            self.cfg.quality_critical_min, behavioral_pass_rate,
        )

        # aggregate token / latency / cost deltas
        tok = [cr["token_deltas"].get("total_token_delta") for cr in case_results]
        lat = [cr["latency_deltas"].get("latency_delta_ms") for cr in case_results]
        cost = [cr["cost_deltas"].get("modeled_cost_delta") for cr in case_results]

        return {
            "baseline_metric_means": baseline_means,
            "tokenwise_metric_means": tokenwise_means,
            "metric_deltas": metric_deltas,
            "baseline_mean_composite": base_mean_comp,
            "tokenwise_mean_composite": tw_mean_comp,
            "quality_preservation_ratio": qpr,
            "quality_gate": gate,
            "behavioral_pass_rate": behavioral_pass_rate,
            "behavioral_count": len(behavioral_results),
            "answer_quality_count": len(case_results),
            "mean_total_token_delta": mean([t for t in tok if t is not None]),
            "mean_latency_delta_ms": mean([l for l in lat if l is not None]),
            "mean_modeled_cost_delta": mean([c for c in cost if c is not None]),
            "roi_percentage": None,
            "roi_status": "operating_cost_not_modeled",
        }


def _flat_scores(cr: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for m, s in cr.get("baseline_scores", {}).items():
        out[f"baseline_{m}"] = s.get("value")
    for m, s in cr.get("tokenwise_scores", {}).items():
        out[f"tokenwise_{m}"] = s.get("value")
    return out


def _short(exc: Exception) -> str:
    msg = str(exc)
    if len(msg) > 200:
        msg = msg[:200] + "..."
    return f"{type(exc).__name__}: {msg}" if msg else type(exc).__name__
