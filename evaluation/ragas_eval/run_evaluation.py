"""CLI entrypoint for the offline MomiHelm Ragas evaluation.

Examples (host-side, from the repo root, using the isolated venv):

    evaluation/.venv/Scripts/python -m evaluation.ragas_eval.run_evaluation --mode smoke
    evaluation/.venv/Scripts/python -m evaluation.ragas_eval.run_evaluation --mode full
    evaluation/.venv/Scripts/python -m evaluation.ragas_eval.run_evaluation --env-check

Targeted grounding remediation (one case, fast metrics only):

    evaluation/.venv/Scripts/python -m evaluation.ragas_eval.run_evaluation ^
      --case-id tw-architecture-001 ^
      --metrics semantic_similarity,tokenwise_grounding_rubric
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .config import EvalConfig, new_run_id, eval_department
from .dataset import load_cases, filter_for_mode, filter_by_case_id, DatasetValidationError
from .experiments import ExperimentRunner, parse_metric_filter
from .metrics import assert_ragas_api, ragas_version
from .reporting import write_artifacts

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


def build_config(mode: str) -> EvalConfig:
    cfg = EvalConfig(mode=mode)
    cfg.run_id = new_run_id(mode)
    cfg.department = eval_department(cfg.run_id)
    return cfg


async def _env_check() -> int:
    """Test A: print version, init embeddings + judge, run one real metric."""
    print(f"[env-check] ragas version: {assert_ragas_api()}")
    cfg = build_config("envcheck")
    runner = ExperimentRunner(cfg)
    health = runner.health_check()
    for name, res in health.items():
        if isinstance(res, dict):
            print(f"[env-check] {name}: ok={res['ok']} ({res['detail']})")
    print(f"[env-check] all_ok={health.get('all_ok')}")

    print("[env-check] running one real Ragas metric (semantic similarity)...")
    s = await runner.engine.score_semantic(
        "envcheck",
        "MomiHelm routes sensitive requests to a local model.",
        "MomiHelm keeps sensitive prompts on a local model.",
    )
    print(f"[env-check] semantic_similarity -> value={s.value} status={s.status}")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "env_check.json").write_text(
        __import__("json").dumps({"ragas_version": ragas_version(), "health": health,
                                  "semantic": s.to_dict()}, indent=2),
        encoding="utf-8")
    return 0 if s.status == "ok" else 1


async def _run(
    mode: str,
    skip_health: bool,
    case_id: str | None = None,
    metrics_raw: str | None = None,
) -> int:
    # Targeted single-case runs use mode label "targeted" in the run id.
    run_mode = "targeted" if case_id else mode
    cfg = build_config(run_mode)
    # Keep EvalConfig.mode as smoke/full for metric defaults when not targeting;
    # for targeted runs use "full" case flags then apply the metric filter.
    plan_mode = mode if mode in ("smoke", "full") else "full"
    if case_id:
        plan_mode = "full"

    print(f"[run] mode={run_mode} run_id={cfg.run_id} dept={cfg.department}")
    print(f"[run] ragas={ragas_version()} judge={cfg.judge_model} embeddings={cfg.embedding_model}")
    if case_id:
        print(f"[run] targeted case_id={case_id}")
    if metrics_raw:
        print(f"[run] metric_filter={metrics_raw}")

    try:
        metric_filter = parse_metric_filter(metrics_raw)
    except ValueError as exc:
        print(f"[run] ERROR: {exc}", file=sys.stderr)
        return 2

    cases, meta = load_cases()
    try:
        if case_id:
            selected = filter_by_case_id(cases, case_id)
        else:
            selected = filter_for_mode(cases, plan_mode)
    except DatasetValidationError as exc:
        print(f"[run] ERROR: {exc}", file=sys.stderr)
        return 2

    answer_n = len([c for c in selected if c.is_answer_quality()])
    behavioral_n = len(selected) - answer_n
    print(f"[run] cases: {len(selected)} ({answer_n} answer-quality, {behavioral_n} behavioral)")

    runner = ExperimentRunner(cfg, metric_filter=metric_filter)

    if not skip_health:
        health = runner.health_check()
        for name, res in health.items():
            if isinstance(res, dict):
                print(f"[health] {name}: ok={res['ok']} ({res['detail']})")
        if not health.get("all_ok"):
            print("[run] WARNING: some health checks failed; continuing (errors will be recorded).")

    print("[run] warming up Ollama...")
    runner.warmup()

    print("[run] executing experiment (sequential; protects local judge)...")
    result = await runner.run(selected, meta, plan_mode)

    dataset_snapshot = {
        "dataset_version": meta.get("dataset_version"),
        "fingerprint": meta.get("fingerprint"),
        "mode": run_mode,
        "targeted": bool(case_id),
        "case_id": case_id,
        "metric_filter": sorted(metric_filter) if metric_filter else None,
        "selected_case_ids": [c.case_id for c in selected],
        "cases": [c.to_dict() for c in selected],
    }
    public_cfg = cfg.to_public_dict()
    public_cfg["targeted"] = bool(case_id)
    public_cfg["case_id"] = case_id
    public_cfg["metric_filter"] = sorted(metric_filter) if metric_filter else None

    run_dir = RESULTS_DIR / cfg.run_id
    written = write_artifacts(run_dir, public_cfg, dataset_snapshot, result)

    agg = result["aggregates"]
    gate = agg.get("quality_gate", {})
    print("\n==== SUMMARY ====")
    print(f"quality_preservation_ratio: {agg.get('quality_preservation_ratio')}")
    print(f"quality_gate_passed:        {gate.get('passed')}  reasons={gate.get('reasons')}")
    print(f"behavioral_pass_rate:       {agg.get('behavioral_pass_rate')}")
    print(f"generator_calls={result['metadata']['generator_calls']} "
          f"judge_calls={result['metadata']['judge_calls']} "
          f"embedding_calls={result['metadata']['embedding_calls']}")
    print(f"errors: {result['metadata']['error_count']}")
    print(f"artifacts: {run_dir}")
    for name, path in written.items():
        print(f"  - {name}: {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MomiHelm offline Ragas evaluation")
    parser.add_argument("--mode", choices=["smoke", "full"], default="smoke")
    parser.add_argument("--env-check", action="store_true",
                        help="Test A: validate env + run one real Ragas metric, then exit.")
    parser.add_argument("--skip-health", action="store_true")
    parser.add_argument(
        "--case-id",
        default=None,
        help="Run exactly one dataset case (targeted remediation). Rejects unknown ids.",
    )
    parser.add_argument(
        "--metrics",
        default=None,
        help=(
            "Comma-separated metric allow-list. Aliases: semantic_similarity, "
            "response_relevancy, factual_correctness, tokenwise_rubric, "
            "tokenwise_grounding_rubric."
        ),
    )
    args = parser.parse_args(argv)

    if args.env_check:
        return asyncio.run(_env_check())
    return asyncio.run(
        _run(args.mode, args.skip_health, case_id=args.case_id, metrics_raw=args.metrics)
    )


if __name__ == "__main__":
    sys.exit(main())
