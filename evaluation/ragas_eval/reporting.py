"""Artifact generation: config.json, CSVs, summary.json, report.md, errors.json.

Includes a defensive secret scrubber so serialized model answers / errors can
never contain real API-key-like tokens.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Optional

from .metrics import M_SEMANTIC, M_RELEVANCY, M_FACTUAL, M_RUBRIC

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{8,}"),
    re.compile(r"gh[pous]_[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[=:]\s*\S+"),
]


def scrub_secrets(value: Any) -> Any:
    """Recursively redact real secret-like tokens from serializable structures."""
    if isinstance(value, str):
        out = value
        for rx in _SECRET_PATTERNS:
            out = rx.sub("[REDACTED_SECRET]", out)
        return out
    if isinstance(value, dict):
        return {k: scrub_secrets(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_secrets(v) for v in value]
    return value


def _write_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(scrub_secrets(data), fh, indent=2, ensure_ascii=False)


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(scrub_secrets({c: row.get(c) for c in columns}))


def write_artifacts(run_dir: Path, config: dict[str, Any], dataset_snapshot: dict[str, Any],
                    result: dict[str, Any]) -> dict[str, str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}

    _write_json(run_dir / "config.json", config)
    written["config"] = str(run_dir / "config.json")

    _write_json(run_dir / "dataset_snapshot.json", dataset_snapshot)
    written["dataset_snapshot"] = str(run_dir / "dataset_snapshot.json")

    case_results = result.get("case_results", [])

    baseline_rows, tokenwise_rows, score_rows, comparison_rows = [], [], [], []
    for cr in case_results:
        b = cr.get("baseline", {})
        t = cr.get("tokenwise", {})
        baseline_rows.append({"case_id": cr["case_id"], **_exec_row(b)})
        tokenwise_rows.append({"case_id": cr["case_id"], **_exec_row(t)})
        score_rows.append(_score_row(cr))
        comparison_rows.append(_comparison_row(cr))

    exec_cols = ["case_id", "provider", "model", "answer_chars", "input_tokens",
                 "output_tokens", "total_tokens", "latency_ms", "actual_cost",
                 "modeled_baseline_cost", "modeled_optimized_cost", "error"]
    _write_csv(run_dir / "baseline_results.csv", baseline_rows, exec_cols)
    written["baseline_results"] = str(run_dir / "baseline_results.csv")
    _write_csv(run_dir / "tokenwise_results.csv", tokenwise_rows, exec_cols)
    written["tokenwise_results"] = str(run_dir / "tokenwise_results.csv")

    score_cols = ["case_id"]
    for m in (M_SEMANTIC, M_RELEVANCY, M_FACTUAL, M_RUBRIC):
        score_cols += [f"baseline_{m}", f"tokenwise_{m}", f"{m}_delta"]
    score_cols += ["baseline_composite", "tokenwise_composite"]
    _write_csv(run_dir / "ragas_scores.csv", score_rows, score_cols)
    written["ragas_scores"] = str(run_dir / "ragas_scores.csv")

    comp_cols = ["case_id", "total_token_delta", "token_reduction_percentage",
                 "latency_delta_ms", "latency_change_percentage", "modeled_cost_delta",
                 "modeled_savings_percentage", "quality_delta"]
    _write_csv(run_dir / "comparison.csv", comparison_rows, comp_cols)
    written["comparison"] = str(run_dir / "comparison.csv")

    summary = {
        "metadata": result.get("metadata", {}),
        "aggregates": result.get("aggregates", {}),
        "ragas_experiment_name": result.get("ragas_experiment_name"),
        "behavioral_results": result.get("behavioral_results", []),
    }
    _write_json(run_dir / "summary.json", summary)
    written["summary"] = str(run_dir / "summary.json")

    # Always write errors.json (empty list when the run is clean) so every
    # experiment folder has a predictable artifact set.
    _write_json(run_dir / "errors.json", result.get("errors") or [])
    written["errors"] = str(run_dir / "errors.json")

    report_md = build_markdown_report(config, dataset_snapshot, result)
    (run_dir / "report.md").write_text(scrub_secrets(report_md), encoding="utf-8")
    written["report"] = str(run_dir / "report.md")

    return written


def _exec_row(e: dict[str, Any]) -> dict[str, Any]:
    ans = e.get("answer") or ""
    return {
        "provider": e.get("provider"),
        "model": e.get("model"),
        "answer_chars": len(ans),
        "input_tokens": e.get("input_tokens"),
        "output_tokens": e.get("output_tokens"),
        "total_tokens": e.get("total_tokens"),
        "latency_ms": e.get("latency_ms"),
        "actual_cost": e.get("actual_cost"),
        "modeled_baseline_cost": e.get("modeled_baseline_cost"),
        "modeled_optimized_cost": e.get("modeled_optimized_cost"),
        "error": e.get("error"),
    }


def _score_row(cr: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {"case_id": cr["case_id"]}
    bs = cr.get("baseline_scores", {})
    ts = cr.get("tokenwise_scores", {})
    for m in (M_SEMANTIC, M_RELEVANCY, M_FACTUAL, M_RUBRIC):
        bv = bs.get(m, {}).get("value")
        tv = ts.get(m, {}).get("value")
        row[f"baseline_{m}"] = bv
        row[f"tokenwise_{m}"] = tv
        row[f"{m}_delta"] = (round(tv - bv, 6) if bv is not None and tv is not None else None)
    row["baseline_composite"] = (cr.get("baseline_composite") or {}).get("composite")
    row["tokenwise_composite"] = (cr.get("tokenwise_composite") or {}).get("composite")
    return row


def _comparison_row(cr: dict[str, Any]) -> dict[str, Any]:
    td = cr.get("token_deltas", {})
    ld = cr.get("latency_deltas", {})
    cd = cr.get("cost_deltas", {})
    bc = (cr.get("baseline_composite") or {}).get("composite")
    tc = (cr.get("tokenwise_composite") or {}).get("composite")
    return {
        "case_id": cr["case_id"],
        "total_token_delta": td.get("total_token_delta"),
        "token_reduction_percentage": td.get("token_reduction_percentage"),
        "latency_delta_ms": ld.get("latency_delta_ms"),
        "latency_change_percentage": ld.get("latency_change_percentage"),
        "modeled_cost_delta": cd.get("modeled_cost_delta"),
        "modeled_savings_percentage": cd.get("modeled_savings_percentage"),
        "quality_delta": (round(tc - bc, 6) if bc is not None and tc is not None else None),
    }


def _fmt(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{v:.4f}" if isinstance(v, float) else str(v)


def build_markdown_report(config: dict[str, Any], dataset_snapshot: dict[str, Any],
                         result: dict[str, Any]) -> str:
    md = result.get("metadata", {})
    agg = result.get("aggregates", {})
    gate = agg.get("quality_gate", {})
    qpr = agg.get("quality_preservation_ratio")

    lines: list[str] = []
    lines.append(f"# MomiHelm Ragas Evaluation Report — run `{md.get('run_id')}`\n")
    lines.append("## Objective\n")
    lines.append(
        "Measure whether the MomiHelm pipeline (guardrails + semantic cache + LangGraph "
        "routing + provider fallback) reduces modeled cost / token usage / unnecessary model "
        "calls while preserving acceptable answer quality, compared with an un-optimized "
        "direct baseline. Ragas is used as an OFFLINE evaluation layer, never in the "
        "real-time request path.\n")

    lines.append("## Architecture\n")
    lines.append("```")
    lines.append("Evaluation Dataset")
    lines.append("├── Direct Baseline Provider (Ollama, no MomiHelm)")
    lines.append("│   └── Baseline Response")
    lines.append("└── MomiHelm n8n Pipeline (guardrails→cache→LangGraph→provider→output guard)")
    lines.append("    └── Optimized Response")
    lines.append("Baseline + Optimized + Reference → Ragas Experiment → Quality Metrics")
    lines.append("→ Token / Cost / Latency Comparison → Evaluation Report")
    lines.append("```\n")

    lines.append("## Configuration\n")
    lines.append(f"- Ragas version: `{md.get('ragas_version')}` (API style: {md.get('ragas_api_style')})")
    lines.append(f"- Judge: `{md.get('judge_provider')}` / `{md.get('judge_model')}`")
    lines.append(f"- Embeddings: `{md.get('embedding_model')}`")
    lines.append(f"- Baseline: `{md.get('baseline_provider')}` / `{md.get('baseline_model')}`")
    lines.append(f"- Mode: `{md.get('mode')}` | Policy mode: `{md.get('policy_mode')}`")
    lines.append(f"- Evaluation department: `{md.get('evaluation_department')}`")
    lines.append(f"- MomiHelm git commit: `{md.get('tokenwise_git_commit')}` (dirty={md.get('tokenwise_git_dirty')})")
    lines.append(f"- Dataset version `{dataset_snapshot.get('dataset_version')}`, "
                 f"fingerprint `{md.get('dataset_fingerprint','')[:16]}...`")
    lines.append(f"- Duration: {md.get('duration_seconds')}s | generator calls: "
                 f"{md.get('generator_calls')} | judge calls: {md.get('judge_calls')} | "
                 f"embedding calls: {md.get('embedding_calls')}")
    lines.append(f"- Ragas experiment: `{result.get('ragas_experiment_name')}`\n")

    lines.append("## Quality metrics (baseline vs MomiHelm)\n")
    lines.append("| Metric | Baseline mean | MomiHelm mean | Delta |")
    lines.append("|---|---|---|---|")
    bmeans = agg.get("baseline_metric_means", {})
    tmeans = agg.get("tokenwise_metric_means", {})
    deltas = agg.get("metric_deltas", {})
    for m in (M_SEMANTIC, M_RELEVANCY, M_FACTUAL, M_RUBRIC):
        lines.append(f"| {m} | {_fmt(bmeans.get(m))} | {_fmt(tmeans.get(m))} | {_fmt(deltas.get(m))} |")
    lines.append("")
    lines.append(f"- Baseline mean composite quality: **{_fmt(agg.get('baseline_mean_composite'))}**")
    lines.append(f"- MomiHelm mean composite quality: **{_fmt(agg.get('tokenwise_mean_composite'))}**")
    lines.append(f"- **quality_preservation_ratio** (MomiHelm derived metric): "
                 f"**{_fmt(qpr)}** (gate ≥ {md.get('quality_gate_ratio')})")
    lines.append("")

    passed = gate.get("passed")
    verdict = "PASSED" if passed else "FAILED"
    lines.append(f"## Quality gate: **{verdict}**\n")
    if gate.get("reasons"):
        for r in gate["reasons"]:
            lines.append(f"- {r}")
    else:
        lines.append("- all sub-conditions satisfied")
    lines.append("")
    if passed:
        lines.append("On this small curated dataset, MomiHelm **preserves acceptable answer "
                     "quality** (quality gate passed) while changing cost/token/latency as shown below.\n")
    else:
        lines.append("The quality gate **did not pass**. MomiHelm quality preservation is NOT "
                     "claimed for this run. See failing cases and metric declines below.\n")

    lines.append("## Behavioral system results\n")
    lines.append(f"- Behavioral pass rate: **{_fmt(agg.get('behavioral_pass_rate'))}** "
                 f"({agg.get('behavioral_count')} cases)")
    lines.append("")
    lines.append("| Case | Expected | Passed | Detail |")
    lines.append("|---|---|---|---|")
    for b in result.get("behavioral_results", []):
        lines.append(f"| {b['case_id']} | {b['expected_behavior']} | {b['passed']} | {b['detail']} |")
    lines.append("")

    lines.append("## Efficiency (token / latency / modeled cost)\n")
    lines.append(f"- Mean total token delta (MomiHelm − baseline): {_fmt(agg.get('mean_total_token_delta'))}")
    lines.append(f"- Mean latency delta ms (MomiHelm − baseline): {_fmt(agg.get('mean_latency_delta_ms'))}")
    lines.append(f"- Mean modeled cost delta (USD): {_fmt(agg.get('mean_modeled_cost_delta'))}")
    lines.append(f"- ROI: `{agg.get('roi_status')}` (roi_percentage={agg.get('roi_percentage')})")
    lines.append("")
    lines.append("> Actual provider API cost is 0 for local Ollama; this does NOT mean the "
                 "infrastructure is free. Modeled costs are illustrative, not real invoices.\n")

    lines.append("## Grounding case (tw-architecture-001)\n")
    grounding = next((c for c in result.get("case_results", [])
                      if c["case_id"] == "tw-architecture-001"), None)
    if grounding:
        rub_b = grounding.get("baseline_scores", {}).get(M_RUBRIC, {})
        rub_t = grounding.get("tokenwise_scores", {}).get(M_RUBRIC, {})
        lines.append(f"- Baseline grounding rubric: {_fmt(rub_b.get('value'))} — {rub_b.get('reason')}")
        lines.append(f"- MomiHelm grounding rubric: {_fmt(rub_t.get('value'))} — {rub_t.get('reason')}")
        lines.append("- The custom rubric penalizes claims of unimplemented capabilities "
                     "(real-time load optimization, autoscaling, learned routing, live provider "
                     "ranking, automatic policy ingestion, real Policy RAG enforcement).")
    else:
        lines.append("- grounding case not included in this run mode")
    lines.append("")

    errs = result.get("errors", [])
    lines.append(f"## Errors & metric failures ({len(errs)})\n")
    if errs:
        lines.append("| Case | Stage | Metric | Type | Error |")
        lines.append("|---|---|---|---|---|")
        for e in errs[:40]:
            lines.append(f"| {e.get('case_id')} | {e.get('stage')} | {e.get('metric')} | "
                         f"{e.get('error_type')} | {e.get('error')} |")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Limitations\n")
    for lim in LIMITATIONS:
        lines.append(f"- {lim}")
    lines.append("")

    lines.append("## Evidence-based conclusion\n")
    if passed:
        lines.append(
            f"MomiHelm preserved acceptable answer quality on this dataset "
            f"(quality_preservation_ratio = {_fmt(qpr)} ≥ {md.get('quality_gate_ratio')}) and "
            f"achieved 100% behavioral safety/privacy correctness. Results are an academic-MVP "
            f"demonstration, not production-grade assurance.")
    else:
        lines.append(
            "The measured results do NOT support a quality-preservation claim for this run. "
            "Failing metrics/cases and likely causes (e.g. local judge variance, small dataset, "
            "generator/judge overlap) are listed above; recommended next steps include prompt "
            "and routing tuning and a larger dataset.")
    lines.append("")
    return "\n".join(lines)


LIMITATIONS = [
    "The dataset is small and curated; appropriate for an academic MVP, not a production SLA.",
    "The same/similar local model may serve as both generator and judge, introducing evaluator bias.",
    "Local Ollama API cost is zero, but infrastructure/compute cost is NOT modeled.",
    "Modeled costs are illustrative and not identical to real provider invoices.",
    "OpenAI and other paid external providers are disabled by default.",
    "Prompt-compression execution is not implemented.",
    "The PyTorch Image Analyser is not yet active; image requests are not evaluated.",
    "Policy Intelligence runtime is not implemented; POST /policy/query is a placeholder.",
    "No full RAG retrieved_contexts are used in generation; the Semantic Cache is NOT RAG.",
    "Langfuse tracing is not implemented yet.",
    "Results demonstrate an academic MVP, not production-grade assurance.",
]
