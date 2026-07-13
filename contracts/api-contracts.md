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
- NOTE: implemented but not yet wired into the n8n workflow (Day 3 scope).

## rag-cache-service

### POST /cache/lookup
Request: `{ "prompt": "...", "dept_id": "demo", "task_type": "general" }`
Response (mock): `{ "cache_status": "miss", "confidence": 0.0, "answer": null }`

### POST /cache/store
Request: `{ "prompt": "...", "answer": "...", "dept_id": "demo" }`
Response: `{ "stored": true }`

### POST /policy/query
Request: `{ "prompt": "...", "k": 3 }`
Response (mock): `{ "policies": [] }`

## image-analyser-service

### POST /analyse
Request: `{ "filename": "screenshot.png" }`  (real bytes later)
Response (mock):
```json
{ "class": "unknown", "confidence": 0.0, "visual_complexity": 0.0, "needs_vision_model": false }
```

## optimizer-service

### POST /agent/run
Request:
```json
{ "request_id": "r1", "prompt": "...", "policy_mode": "balanced",
  "guardrail_status": "passed", "cache_status": "miss" }
```
Response (mock):
```json
{ "selected_tier": "cheap", "estimated_tokens": 42, "estimated_cost": 0.00021,
  "optimization_reason": "Low complexity, no sensitive data -> cheap tier (mock)",
  "cost_saved": 0.0018 }
```

## Final response returned by n8n to the UI

```json
{
  "answer": "This is a mock answer from TokenWise.",
  "receipt": {
    "guardrail_status": "passed",
    "cache_status": "miss",
    "selected_tier": "cheap",
    "estimated_tokens": 42,
    "estimated_cost": 0.00021,
    "optimization_reason": "Low complexity, no sensitive data -> cheap tier (mock)",
    "cost_saved": 0.0018
  }
}
```

## Error handling (skeleton convention)
Services return HTTP 200 with the shapes above for the happy path. On unexpected
errors they return `{"error": {"code": "INTERNAL", "message": "..."}}` with an
appropriate 4xx/5xx status. Real validation and richer error codes come later.
