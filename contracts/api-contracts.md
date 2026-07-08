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

## guardrails-service

### POST /check/input
Request:
```json
{ "request_id": "r1", "prompt": "How do I reset my password?", "policy_mode": "balanced" }
```
Response (mock):
```json
{ "guardrail_status": "passed", "reason": null, "contains_sensitive_data": false,
  "require_local_model": false, "cost_saved_by_blocking": 0 }
```

### POST /check/output
Request: `{ "request_id": "r1", "answer": "..." }`
Response: `{ "guardrail_status": "passed", "redacted_text": null }`

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
