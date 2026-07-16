"""CLI entrypoint for the offline TokenWise Ragas evaluation.

Examples (host-side, from the repo root, using the isolated venv):

    evaluation/.venv/Scripts/python -m evaluation.ragas_eval.run_evaluation --mode smoke
    evaluation/.venv/Scripts/python -m evaluation.ragas_eval.run_evaluation --mode full
    evaluation/.venv/Scripts/python -m evaluation.ragas_eval.run_evaluation --env-check
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .config import EvalConfig, new_run_id, eval_department
from .dataset import load_cases, filter_for_mode
from .experiments import ExperimentRunner
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
        "TokenWise routes sensitive requests to a local model.",
        "TokenWise keeps sensitive prompts on a local model.",
    )
    print(f"[env-check] semantic_similarity -> value={s.value} status={s.status}")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "env_check.json").write_text(
        __import__("json").dumps({"ragas_version": ragas_version(), "health": health,
                                  "semantic": s.to_dict()}, indent=2),
        encoding="utf-8")
    return 0 if s.status == "ok" else 1


async def _run(mode: str, skip_health: bool) -> int:
    cfg = build_config(mode)
    print(f"[run] mode={mode} run_id={cfg.run_id} dept={cfg.department}")
    print(f"[run] ragas={ragas_version()} judge={cfg.judge_model} embeddings={cfg.embedding_model}")

    cases, meta = load_cases()
    selected = filter_for_mode(cases, mode)
    answer_n = len([c for c in selected if c.is_answer_quality()])
    behavioral_n = len(selected) - answer_n
    print(f"[run] cases: {len(selected)} ({answer_n} answer-quality, {behavioral_n} behavioral)")

    runner = ExperimentRunner(cfg)

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
    result = await runner.run(selected, meta, mode)

    # snapshot the exact selected dataset (curated, safe to store)
    dataset_snapshot = {
        "dataset_version": meta.get("dataset_version"),
        "fingerprint": meta.get("fingerprint"),
        "mode": mode,
        "selected_case_ids": [c.case_id for c in selected],
        "cases": [c.to_dict() for c in selected],
    }
    run_dir = RESULTS_DIR / cfg.run_id
    written = write_artifacts(run_dir, cfg.to_public_dict(), dataset_snapshot, result)

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
    parser = argparse.ArgumentParser(description="TokenWise offline Ragas evaluation")
    parser.add_argument("--mode", choices=["smoke", "full"], default="smoke")
    parser.add_argument("--env-check", action="store_true",
                        help="Test A: validate env + run one real Ragas metric, then exit.")
    parser.add_argument("--skip-health", action="store_true")
    args = parser.parse_args(argv)

    if args.env_check:
        return asyncio.run(_env_check())
    return asyncio.run(_run(args.mode, args.skip_health))


if __name__ == "__main__":
    sys.exit(main())
