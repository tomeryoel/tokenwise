# TokenWise - API Contracts (v0, walking skeleton)

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
| Too short (<3 words) | false | too_short_or_low_value_prompt | low_value_prompt | cost_governance |
| Off-topic | false | off_topic_cost_block | off_topic | cost_governance |
| Otherwise | true | passed | null | null |

Secrets/PII populate `safe_text` / `redacted_text` with `[REDACTED_SECRET]`,
`[REDACTED_EMAIL]`, `[REDACTED_PHONE]`, `[REDACTED_ID]`. Short-command
exceptions ("summarize this", "translate this", "explain this") bypass the
too-short rule.

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
{ "query": "How can TokenWise reduce LLM costs?", "dept_id": "support",
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

### POST /policy/query
Request: `{ "prompt": "...", "k": 3 }`
Response (basic placeholder): `{ "policies": [] }`

## image-analyser-service

### POST /analyse
Request: `{ "filename": "screenshot.png" }`  (real bytes later)
Response (mock):
```json
{ "class": "unknown", "confidence": 0.0, "visual_complexity": 0.0, "needs_vision_model": false }
```

## optimizer-service (Day 5: real LangGraph Optimization Engine)

A deterministic multi-node **LangGraph** state graph (`graph.py`) turns request
signals into a structured Optimization Plan. No LLM is used inside the graph.

**Graph nodes (in order):** `normalize_inputs -> classify_task ->
estimate_complexity -> evaluate_sensitivity -> evaluate_cache_signal ->
apply_policy_mode -> decide_compression -> select_model_tier ->
build_fallback_plan -> calculate_estimated_savings -> build_optimization_plan`.

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
  "allow_external_model": true, "estimated_tokens": 7,
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

## Final response returned by n8n to the UI

Cache miss (model path):
```json
{
  "answer": "This is a mock answer from TokenWise.",
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
  "answer": "This is a mock answer from TokenWise.",
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
