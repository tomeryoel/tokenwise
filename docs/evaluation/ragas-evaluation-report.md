# TokenWise Ragas Evaluation Report

**Canonical reviewed report** for the academic MVP (lecturer requirement: real Ragas evaluation).

| Field | Value |
|---|---|
| Source run | `20260716T172322Z-full-857f5612` (full mode) |
| Smoke companion | `20260716T131911Z-smoke-14001654` (gate passed on a smaller metric set) |
| Ragas version | `0.4.3` |
| API style | `@experiment()` + `ragas.metrics.collections` (not deprecated `evaluate()`) |
| Git commit at run time | `3c83790` (working tree had uncommitted docs/progress logging) |

Associated machine-readable files in this folder:
`ragas-evaluation-summary.json`, `ragas-evaluation-comparison.csv`.

## Objective

Measure whether the TokenWise pipeline (guardrails + semantic cache + LangGraph routing + provider fallback) reduces modeled cost / token usage / unnecessary model calls while preserving acceptable answer quality, compared with an un-optimized direct baseline. Ragas is used as an OFFLINE evaluation layer, never in the real-time request path.

## Architecture

```
Evaluation Dataset
├── Direct Baseline Provider (Ollama, no TokenWise)
│   └── Baseline Response
└── TokenWise n8n Pipeline (guardrails→cache→LangGraph→provider→output guard)
    └── Optimized Response
Baseline + Optimized + Reference → Ragas Experiment → Quality Metrics
→ Token / Cost / Latency Comparison → Evaluation Report
```

## Configuration

- Ragas version: `0.4.3` (API style: experiment+collections (0.4.x))
- Judge: `ollama` / `llama3.1:latest`
- Embeddings: `sentence-transformers/all-MiniLM-L6-v2`
- Baseline: `ollama` / `llama3.1:latest`
- Mode: `full` | Policy mode: `balanced`
- Evaluation department: `ragas-eval-20260716T172322Z-full-857f5612`
- TokenWise git commit: `3c8379001c2443a0b264c76d9446d2766021c345` (dirty=True)
- Dataset version `1.0.0`, fingerprint `0d9d244267e47fab...`
- Duration: 3189.0s | generator calls: 22 | judge calls: 26 | embedding calls: 26
- Ragas experiment: `20260716T172322Z-full-857f5612-full`

## Quality metrics (baseline vs TokenWise)

| Metric | Baseline mean | TokenWise mean | Delta |
|---|---|---|---|
| semantic_similarity | 0.7996 | 0.8194 | 0.0199 |
| response_relevancy | 0.7588 | 0.6841 | -0.0747 |
| factual_correctness | 0.5000 | 0.5000 | 0.0000 |
| tokenwise_rubric | 0.5000 | 0.6667 | 0.1667 |

- Baseline mean composite quality: **0.7575**
- TokenWise mean composite quality: **0.7647**
- **quality_preservation_ratio** (TokenWise derived metric): **1.0094** (gate ≥ 0.9)

## Quality gate: **FAILED**

- a quality-critical case scored below 0.6

The quality gate **did not pass**. TokenWise quality preservation is NOT claimed for this run. See failing cases and metric declines below.

## Behavioral system results

- Behavioral pass rate: **1.0000** (5 cases)

| Case | Expected | Passed | Detail |
|---|---|---|---|
| beh-guardrail-injection-009 | block | True | ok |
| beh-guardrail-secret-010 | block | True | ok |
| beh-guardrail-offtopic-011 | block | True | ok |
| beh-privacy-pii-012 | redact_local | True | ok |
| beh-cache-repeat-013 | cache_hit | True | ok |

## Efficiency (token / latency / modeled cost)

- Mean total token delta (TokenWise − baseline): -57.8750
- Mean latency delta ms (TokenWise − baseline): -26016.0762
- Mean modeled cost delta (USD): -0.0059
- ROI: `operating_cost_not_modeled` (roi_percentage=None)

> Actual provider API cost is 0 for local Ollama; this does NOT mean the infrastructure is free. Modeled costs are illustrative, not real invoices.

## Grounding case (tw-architecture-001)

- Baseline grounding rubric: n/a — None
- TokenWise grounding rubric: 0.2500 — The response accurately describes TokenWise's hybrid approach to choosing between a local model and an external model, considering factors like user environment, data sensitivity, and performance requirements. However, it contradicts the reference by stating that the decision is made in real-time based on device specs, available memory, and user-defined preferences, whereas the reference indicates that the decision is deterministic and rule-based through LangGraph. | raw_1_5=2.0
- The custom rubric penalizes claims of unimplemented capabilities (real-time load optimization, autoscaling, learned routing, live provider ranking, automatic policy ingestion, real Policy RAG enforcement).

## Errors & metric failures (10)

| Case | Stage | Metric | Type | Error |
|---|---|---|---|---|
| tw-architecture-001 | metric | response_relevancy | metric_error | TimeoutError: metric exceeded 120.0s |
| tw-architecture-001 | metric | factual_correctness | metric_error | TimeoutError: metric exceeded 120.0s |
| tw-architecture-001 | metric | tokenwise_rubric | metric_error | TimeoutError: metric exceeded 120.0s |
| tw-architecture-001 | metric | factual_correctness | metric_error | TimeoutError: metric exceeded 120.0s |
| tw-cache-002 | metric | factual_correctness | metric_error | TimeoutError: metric exceeded 120.0s |
| tw-cache-002 | metric | factual_correctness | metric_error | TimeoutError: metric exceeded 120.0s |
| gen-summarize-006 | metric | factual_correctness | metric_error | TimeoutError: metric exceeded 120.0s |
| gen-summarize-006 | metric | factual_correctness | metric_error | TimeoutError: metric exceeded 120.0s |
| gen-reason-008 | metric | factual_correctness | metric_error | TimeoutError: metric exceeded 120.0s |
| gen-reason-008 | metric | factual_correctness | metric_error | TimeoutError: metric exceeded 120.0s |

## Limitations

- The dataset is small and curated; appropriate for an academic MVP, not a production SLA.
- The same/similar local model may serve as both generator and judge, introducing evaluator bias.
- Local Ollama API cost is zero, but infrastructure/compute cost is NOT modeled.
- Modeled costs are illustrative and not identical to real provider invoices.
- OpenAI and other paid external providers are disabled by default.
- Prompt-compression execution is not implemented.
- The PyTorch Image Analyser is not yet active; image requests are not evaluated.
- Policy Intelligence runtime is not implemented; POST /policy/query is a placeholder.
- No full RAG retrieved_contexts are used in generation; the Semantic Cache is NOT RAG.
- At evaluation time Langfuse tracing was not implemented; Day 9 added it later and
  it did not affect these preserved results.
- Results demonstrate an academic MVP, not production-grade assurance.

## Evidence-based conclusion

The measured results do NOT support a quality-preservation claim for this run. Failing metrics/cases and likely causes (e.g. local judge variance, small dataset, generator/judge overlap) are listed above; recommended next steps include prompt and routing tuning and a larger dataset.

---

## Follow-up: targeted grounding remediation (tw-architecture-001)

The original full-run failure above remains the evidence that Ragas found a real defect: TokenWise product answers were ungrounded and invented unsupported capabilities (e.g. real-time / device-spec routing). That original report is **preserved** and is **not** rewritten as a pass.

### Root cause

Provider prompts branded the model as TokenWise but injected no product capability facts. Only the user prompt plus a generic system line was sent, so the LLM invented plausible features.

### Remediation (runtime)

- Source of truth: `services/optimizer-service/config/tokenwise_capabilities.json` (`implemented` / `partial_or_planned` / `unsupported`).
- Deterministic detector + grounded system prompt: `services/optimizer-service/providers/grounding.py` (no extra LLM classification call).
- Wired in `providers/executor.py`; n8n Provider Execute may pass compact `runtime_facts` (not a full Decision Receipt).

### Targeted re-validation (not a full/smoke rerun)

| Field | Value |
|---|---|
| Run | `20260718T202550Z-targeted-92c63ab8` |
| Case | `tw-architecture-001` only |
| Metrics | `semantic_similarity`, `tokenwise_grounding_rubric` only |
| FactualCorrectness | **not run** |
| Smoke / full dataset | **not run** |
| Duration | 426.85s |
| Generator calls | 2 |
| Judge calls | 2 |

| Metric | Baseline | TokenWise | Before (full run TokenWise) |
|---|---|---|---|
| Semantic Similarity | 0.5563 | **0.8927** | 0.8194 (full-run mean; case had timeouts on other metrics) |
| Grounding Rubric (normalized) | 0.2500 | **0.7500** (raw 4/5) | **0.2500** (raw 2/5) |

Judge reason after remediation: accurate decision-flow description (guardrails, semantic cache, LangGraph rule-based routing, policy_mode); minor omissions vs reference — **no unsupported capability claims**.

### Targeted verdict

**Targeted grounding remediation still failed** the recommended Grounding Rubric ≥ 0.80 bar (achieved 0.75). Unsupported claims were eliminated and Semantic Similarity was produced successfully. This does **not** mean the complete project quality gate now passes — full evaluation was not rerun.
