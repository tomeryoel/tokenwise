# MomiHelm - API Contracts (v0, walking skeleton)

These are the minimal contracts used by the Day 1-2 skeleton. Responses are mostly
mocked. Fields are intentionally stable so real logic can be dropped in later without
changing the n8n workflow or the React UI.

All services listen on port 8000 inside their container. Host ports (docker-compose):

| Service | Host port | Container port |
|---|---|---|
| guardrails-service | 8001 | 8000 |
| rag-cache-service | 8002 | 8000 |
| image-analyser-service | 8003 | 8000 |
| optimizer-service | 8004 | 8000 |

Every service exposes `GET /health -> {"status": "ok", "service": "<name>"}`.

## guardrails-service (Day 3: real MVP rules)

### POST /check/input
Request:
```json
{ "request_id": "r1", "prompt": "How do I reset my password?", "policy_mode": "balanced" }
```
Response (full contract; values depend on the rules that fire):
```json
{
  "pass": true,
  "reason": "passed",
  "policy_triggered": null,
  "severity": "low",
  "detected_risk_type": null,
  "contains_sensitive_data": false,
  "requires_redaction": false,
  "recommended_route": "external",
  "allow_external_model": true,
  "require_local_model": false,
  "require_human_approval": false,
  "estimated_cost_risk": "low",
  "estimated_tokens": 7,
  "cost_saved_by_blocking": 0.0,
  "cost_control_action": "standard",
  "cost_control_reason": null,
  "prefer_low_cost_tier": false,
  "safe_text": "How do I reset my password?",
  "redacted_text": null
}
```

Rule outcomes (checked in this order):

| Rule | pass | reason | detected_risk_type | policy_triggered |
|---|---|---|---|---|
| Empty / whitespace | false | empty_prompt | low_value_prompt | cost_governance |
| Prompt injection | false | prompt_injection_detected | prompt_injection | safety_governance |
| Secret / API key | false | secret_detected | secret | safety_governance |
| PII (email/phone/id) | true | pii_detected_redacted | pii | safety_governance |
| Obvious noise / no meaningful content | false | non_meaningful_prompt | low_value_prompt | cost_governance |
| Short / low-context prompt | true | low_context_cost_optimization | null | cost_governance |
| Otherwise | true | passed | null | null |

Secrets/PII populate `safe_text` / `redacted_text` with `[REDACTED_SECRET]`,
`[REDACTED_EMAIL]`, `[REDACTED_PHONE]`, `[REDACTED_ID]`. Topic is never used as
a block condition. Short but meaningful prompts pass with
`prefer_low_cost_tier=true`; n8n forwards that signal to LangGraph, which caps
eligible low/medium-complexity requests at the cheap tier without overriding a
high quality requirement.

### POST /check/output
Request: `{ "request_id": "r1", "answer": "..." }`
Response: `{ "pass": true, "issues": [], "redacted_text": null }`
- Redacts leaked secrets (adds issue `leaked_secret_redacted`).
- Flags unsupported ROI claims (e.g. "guaranteed savings", "100% cost reduction",
  "always saves money") as `unsupported_roi_claim:<phrase>` and sets `pass=false`.
- Wired into the n8n workflow: runs on both the model answer (cache miss) and the
  cached answer (cache hit) before responding.

## rag-cache-service (Day 4: real semantic cache)

Real semantic cache backed by **sentence-transformers/all-MiniLM-L6-v2** (CPU)
embeddings and **ChromaDB** persistent storage.

- **Normalization:** trim, collapse whitespace, lowercase (embeddings normalized).
- **Similarity space:** Chroma `hnsw:space=cosine`. `query()` returns a cosine
  *distance* = `1 - cosine_similarity`.
- **Distance -> confidence:** `confidence = clamp(1 - distance, 0.0, 1.0)`.
  A larger distance always means a lower confidence.
- **Threshold:** default `0.88`, from env `CACHE_SIMILARITY_THRESHOLD` and
  overridable per-request via the `threshold` field.
- **Department isolation:** lookups filter Chroma by `where={"dept_id": <dept>}`,
  so `support` entries are never returned for `engineering`. Default dept when
  the caller omits one is `demo-support`.
- **Sensitive-data exclusion:** requests with `contains_sensitive_data=true` are
  neither searched nor stored.
- **Persistence:** Chroma data lives at `/app/data/chroma` on the `rag_cache_data`
  named volume (HF model cached at `/app/data/hf`), so entries and the model
  survive container restarts.
- **Cost model:** deterministic `$0.03 / 1k tokens` premium baseline; on a hit
  `cost_saved = estimated_tokens * 0.00003`.

### POST /cache/lookup
Request:
```json
{ "query": "How can MomiHelm reduce LLM costs?", "dept_id": "support",
  "task_type": "general", "threshold": 0.88, "contains_sensitive_data": false }
```
Response on hit:
```json
{ "hit": true, "confidence": 0.94, "answer": "...", "entry_id": "ab12...",
  "dept_id": "support", "estimated_tokens": 16, "cost_saved": 0.00048,
  "threshold": 0.88, "reason": "semantic_cache_hit" }
```
Response on miss:
```json
{ "hit": false, "confidence": 0.62, "answer": null, "entry_id": null,
  "dept_id": "support", "estimated_tokens": 16, "cost_saved": 0.0,
  "threshold": 0.88, "reason": "below_similarity_threshold" }
```
Other `reason` values: `sensitive_request_not_cacheable`, `empty_query`,
`no_entries_for_dept`. (`query` is preferred; `prompt` still accepted.)

### POST /cache/store
Request:
```json
{ "query": "...", "answer": "...", "dept_id": "support", "task_type": "general",
  "contains_sensitive_data": false, "output_guardrail_passed": true }
```
Response: `{ "stored": true, "entry_id": "ab12...", "reason": "stored" }`

Storage is skipped (with `stored: false` and a `reason`) when
`contains_sensitive_data=true` (`sensitive_not_cacheable`),
`output_guardrail_passed=false` (`output_guardrail_failed`),
empty query (`empty_query`), or empty answer (`empty_answer`).

### POST /policy/query (Policy Evidence Retrieval — placeholder)
Request: `{ "prompt": "...", "k": 3 }`
Response (basic placeholder): `{ "policies": [] }`

This endpoint is the intended home of **Policy Evidence Retrieval** (RAG over uploaded
policy documents for clauses, source references, and audit evidence). It is **not**
implemented: the handler ignores `prompt`/`k` and always returns an empty list, no policy
vector collection is seeded, and n8n never calls it. It is **not** a source of truth for
runtime enforcement — hard routing/privacy/budget/provider decisions come from the
**Structured Policy Engine** (today: the `policy_mode` config). See
[../docs/policy-intelligence-design.md](../docs/policy-intelligence-design.md).

## image-analyser-service (Day 8: PyTorch ResNet18)

### POST /analyse
Request (with image bytes):
```json
{ "filename": "screenshot.png", "image_base64": "<base64-encoded bytes>" }
```
Response:
```json
{
  "class": "screenshot",
  "confidence": 0.72,
  "visual_complexity": 0.61,
  "needs_vision_model": true,
  "model": "resnet18",
  "weights": "IMAGENET1K_V1",
  "inference_ms": 42.5
}
```

Coarse classes: `screenshot`, `diagram`, `chart`, `document_photo`. When
`image_base64` is omitted the service returns the legacy stub
(`class=unknown`, `visual_complexity=0.0`). Response also includes `model`
(`resnet18`), `weights` (`IMAGENET1K_V1`), and `inference_ms`.

Invalid / empty / corrupt / oversized (>5 MiB) payloads return HTTP 400 with
`{"code":"INVALID_IMAGE","message":"..."}`.

Image requests from the Playground send base64 in the n8n webhook body
(in-memory only — never stored in browser persistent storage). n8n calls
`image-analyser-service` when `has_image=true`, forwards
`has_image` / `image_class` / `image_complexity` to the optimizer, skips
semantic cache lookup, and returns a vision-tier receipt when
`visual_complexity >= 0.5`.

This is classification for routing, **not** OCR and **not** multimodal LLM
captioning.

## optimizer-service (Day 5: real LangGraph Optimization Engine)

A deterministic, **conditional** **LangGraph** state graph (`graph.py`) turns
request signals into a structured Optimization Plan. No LLM is used inside the
graph.

**Shared prefix:** `normalize_inputs -> classify_task -> estimate_complexity ->
evaluate_sensitivity -> evaluate_cache_signal -> route_request_path`.

**Conditional edge #1 (`route_request_path`)** dispatches to one of five paths:
`reject_path` (guardrail blocked), `cache_path` (cache hit >= 0.88),
`local_only_path` (sensitive/require_local), `vision_path` (image complexity >= 0.5),
or `standard_optimization_path`.

**Standard path:** `apply_policy_mode -> {decide_compression | skip_compression}
-> select_model_tier -> build_fallback_plan`.

**Conditional edge #2 (`should_recommend_compression`)** runs `decide_compression`
only for long-enough prompts, else `skip_compression`.

**Convergence:** all paths -> `calculate_estimated_savings -> build_optimization_plan`.

The response also carries graph observability: `graph_path`, `branch_reason`, and
`executed_nodes` (only nodes that actually ran; skipped branches never appear).
See `docs/architecture.md` for the Mermaid diagram and the print-graph command.

**Routing tiers:** `local | cheap | balanced | premium | vision | reject | cache | fallback`.

**Static price table (USD / 1k tokens):** local `0.00005`, cheap `0.0005`,
balanced `0.003`, premium `0.03`, vision `0.01`, cache/reject `0.0`.
`baseline = premium price`, `optimized = selected tier price`,
`savings = max(0, baseline - optimized)` (never negative).

**Complexity score (0-1):** length signal (cap 0.30) + task-type weight +
reasoning-keyword density + code/doc bump + image-complexity bump + quality floor.
Levels: `<=0.30 low`, `<=0.65 medium`, `>0.65 high`.

**Policy modes:** `conservative` (protect quality, minimal compression),
`balanced` (cheapest tier meeting quality), `aggressive` (prefer local/cheap,
compress earlier). The same prompt can yield different plans per mode.

### POST /agent/run
Request (signals forwarded by n8n from normalize + guardrails + cache):
```json
{ "request_id": "r1", "prompt": "...", "policy_mode": "balanced",
  "guardrail_status": "passed", "guardrail_reason": "passed",
  "cache_status": "miss", "cache_confidence": 0.0,
  "contains_sensitive_data": false, "require_local_model": false,
  "allow_external_model": true, "prefer_low_cost_tier": false,
  "estimated_tokens": 7,
  "has_image": false, "image_complexity": 0.0, "max_cost": null }
```
Response (rich plan + legacy compatibility fields):
```json
{
  "request_id": "r1",
  "task_type": "support_request",
  "complexity_score": 0.25,
  "complexity_level": "low",
  "selected_tier": "cheap",
  "compression_recommended": false,
  "compression_target_ratio": 1.0,
  "compression_reason": "prompt is already short; no compression needed",
  "compression_risk": "low",
  "fallback_tier": "balanced",
  "fallback_reason": "cheap fails quality validation -> balanced",
  "escalation_conditions": ["cheap/balanced fail quality check -> escalate one tier"],
  "estimated_baseline_cost": 0.00021,
  "estimated_optimized_cost": 0.0000035,
  "estimated_savings": 0.0002065,
  "decision_reasons": ["task_type=support_request (...)", "complexity=0.25 (low) ...", "..."],
  "graph_path": "standard_optimization_path",
  "branch_reason": "normal non-sensitive cache-miss request",
  "executed_nodes": ["normalize_inputs", "classify_task", "estimate_complexity",
    "evaluate_sensitivity", "evaluate_cache_signal", "route_request_path",
    "apply_policy_mode", "skip_compression", "select_model_tier",
    "build_fallback_plan", "calculate_estimated_savings", "build_optimization_plan"],
  "optimization_plan": { "route": "cheap", "compress": false, "compression_target_ratio": 1.0,
    "local_only": false, "allow_external": true, "fallback_tier": "balanced" },
  "estimated_tokens": 7,
  "estimated_cost": 0.0000035,
  "cost_saved": 0.0002065,
  "optimization_reason": "support_request/low -> cheap tier [balanced]"
}
```
Legacy compatibility fields preserved for n8n/React: `selected_tier`,
`estimated_tokens`, `estimated_cost`, `cost_saved`, `optimization_reason`.

Unit tests: `cd services/optimizer-service && pip install -r requirements.txt pytest && python -m pytest -q`.

### GET /providers/health
Returns Ollama reachability, installed models, configured models, and OpenAI
enablement status. Does not expose API keys. Fast enough for diagnostics; the
main `GET /health` remains instant.

### POST /providers/execute (Day 6: real Layer 4 execution)
Executes the LangGraph-selected tier against configured providers (Ollama local,
optional OpenAI). Packaged inside optimizer-service to preserve the four-service
architecture; may be extracted to a dedicated gateway in a commercial version.

Request:
```json
{ "request_id": "req-123", "prompt": "How can MomiHelm reduce LLM cost?",
  "selected_tier": "cheap", "fallback_tier": "balanced", "policy_mode": "balanced",
  "contains_sensitive_data": false, "require_local_model": false,
  "allow_external_model": true, "estimated_tokens": 20,
  "estimated_baseline_cost": 0.001, "estimated_optimized_cost": 0.0001,
  "optimization_plan": { "route": "cheap", "local_only": false, "allow_external": true },
  "prompt_redaction_applied": false }
```
Response (success):
```json
{ "success": true, "answer": "...", "provider": "ollama", "model": "llama3.1:latest",
  "requested_tier": "cheap", "executed_tier": "cheap",
  "actual_input_tokens": 18, "actual_output_tokens": 42, "actual_total_tokens": 60,
  "actual_cost": 0.0, "actual_cost_saved": 0.001, "latency_ms": 1234,
  "used_fallback": true, "fallback_reason": "external_provider_not_configured",
  "privacy_enforced": false, "prompt_redaction_applied": false,
  "cost_calculation_status": "local_zero_api_cost",
  "actual_execution_attempt_count": 1,
  "attempts": [
    { "provider": "openai", "tier": "cheap", "executed": false, "success": false,
      "attempt_role": "configuration_check", "error_code": "PROVIDER_NOT_CONFIGURED" },
    { "provider": "ollama", "tier": "cheap", "model": "llama3.1:latest",
      "executed": true, "success": true, "attempt_role": "primary" }
  ] }
```

**Attempt semantics:** `attempts` may list configuration checks (no HTTP call) plus
actual executions. `actual_execution_attempt_count` is capped at **2** (one primary,
one fallback). Items with `executed=false` and `attempt_role=configuration_check`
are skipped candidates, not model calls.

**Pricing:** `config/model_pricing.json` (per-million input/output tokens).
Ollama actual_cost=0 (local_zero_api_cost). Unknown paid models → actual_cost=null,
cost_calculation_status=pricing_not_configured.

### POST /usage/log (Day 7 persistence + Day 9 observability)
Logs a terminal request outcome. Computes `prompt_fingerprint` server-side (SHA-256
of normalized prompt). Does not store raw prompt text. When Langfuse is enabled,
the same privacy-safe fingerprint and structured terminal facts are exported after
SQLite persistence; raw prompt and answer content are never exported.

Idempotency: `request_id` is unique; retries upsert the same usage row and reuse an
already-exported deterministic trace instead of creating a second trace.

Response:
```json
{
  "logged": true,
  "request_id": "r-123",
  "duplicate": false,
  "tracing_enabled": true,
  "trace_exported": true,
  "trace_id": "5c37123a76aa98d3346f7da5f22b9e5a",
  "trace_url": "http://langfuse-web:3000/project/tokenwise-project/traces/...",
  "trace_error": null
}
```

Tracing is fail-open. If Langfuse is disabled, incomplete, or temporarily
unavailable, usage persistence still succeeds and the response reports
`trace_exported=false` with a bounded diagnostic in `trace_error` when applicable.

### GET /observability/status (Day 9)
Returns credential-safe runtime and export status:
```json
{
  "requested_enabled": true,
  "configured": true,
  "active": true,
  "client_ready": true,
  "base_url": "http://langfuse-web:3000",
  "public_url": "http://localhost:3000",
  "environment": "development",
  "release": "tokenwise-day-9",
  "exported_traces": 2,
  "failed_exports": 0,
  "pending_exports": 0,
  "initialization_error": null
}
```

### GET /observability/traces/{request_id} (Day 9)
Returns the local export record for one MomiHelm request:
```json
{
  "request_id": "r-123",
  "found": true,
  "exported": true,
  "attempt_count": 1,
  "trace_id": "5c37123a76aa98d3346f7da5f22b9e5a",
  "trace_url": "http://langfuse-web:3000/project/tokenwise-project/traces/...",
  "last_error": null
}
```

Unknown request IDs return HTTP 200 with `found=false`. Neither observability
endpoint exposes API keys, prompts, answers, PII, or secrets.

### GET /usage/summary?period_days=30&dept_id=optional
Returns aggregated metrics. Primary savings per request uses `actual_cost_saved`
when known, else `estimated_savings`. `roi_percentage` is null;
`roi_status=operating_cost_not_modeled`.

### GET /usage/recent?limit=20&dept_id=optional
Privacy-safe recent requests (no prompt content).

### GET /webhook/tokenwise-usage-summary (n8n → browser)
Read-only n8n webhook proxies `GET /usage/summary` with CORS for the Dashboard.

## Final response returned by n8n to the UI

Cache miss (model path):
```json
{
  "answer": "This is a mock answer from MomiHelm.",
  "receipt": {
    "guardrail_status": "passed",
    "output_guardrail_status": "passed",
    "output_guardrail_issues": [],
    "cache_status": "miss",
    "cache_confidence": 0.61,
    "cache_entry_id": null,
    "selected_tier": "cheap",
    "estimated_tokens": 16,
    "estimated_cost": 0.000008,
    "optimization_reason": "[MOCK] policy_mode=balanced, cache=miss ... -> cheap tier",
    "cost_saved": 0.000472,
    "savings_source": "model_routing",
    "savings_reason": "cheaper_model_selected"
  }
}
```

Cache hit (semantic cache path - optimizer and model skipped):
```json
{
  "answer": "This is a mock answer from MomiHelm.",
  "receipt": {
    "guardrail_status": "passed",
    "output_guardrail_status": "passed",
    "cache_status": "hit",
    "cache_confidence": 0.94,
    "cache_entry_id": "ab12...",
    "selected_tier": "cache",
    "estimated_tokens": 16,
    "estimated_cost": 0,
    "optimization_reason": "semantic_cache_hit",
    "cost_saved": 0.00048,
    "savings_source": "semantic_cache",
    "savings_reason": "semantic_cache_hit"
  }
}
```

## Error handling (skeleton convention)
Services return HTTP 200 with the shapes above for the happy path. On unexpected
errors they return `{"error": {"code": "INTERNAL", "message": "..."}}` with an
appropriate 4xx/5xx status. Real validation and richer error codes come later.
