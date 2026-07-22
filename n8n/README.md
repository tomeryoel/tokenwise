# n8n Setup (walking skeleton)

The workflow file `tokenwise-skeleton.workflow.json` implements Layer 2:

`Webhook -> Normalize -> Guardrails -> Cache -> Optimizer -> Provider Execute -> Output Guardrails -> Cache Store -> Build Response -> Respond to Webhook`

Cache hits and blocked inputs short-circuit before provider execution.

## Import and activate

1. Start the stack: from the repo root run `docker compose up --build`.
2. Open n8n at http://localhost:5679 and complete the first-run owner setup
   (local account; nothing leaves your machine).
3. Top-right menu -> **Import from File** -> choose
   `n8n/tokenwise-skeleton.workflow.json`.
4. Click **Save**, then toggle **Active** (top-right) so the production webhook
   URL is live.

### Re-import after workflow JSON changes (Day 6+)

When `tokenwise-skeleton.workflow.json` changes in git, the running n8n container
does **not** pick it up automatically. Re-import and publish:

```powershell
docker cp n8n/tokenwise-skeleton.workflow.json tokenwise-n8n-1:/tmp/tokenwise-workflow.json
docker exec tokenwise-n8n-1 n8n import:workflow --input=/tmp/tokenwise-workflow.json
docker exec tokenwise-n8n-1 n8n publish:workflow --id=tokenwiseskeleton
docker restart tokenwise-n8n-1
```

Also import the usage-summary webhook (Day 7 Dashboard and Day 10 ROI):

```powershell
docker cp n8n/tokenwise-usage-summary.workflow.json tokenwise-n8n-1:/tmp/usage-summary.json
docker exec tokenwise-n8n-1 n8n import:workflow --input=/tmp/usage-summary.json
docker exec tokenwise-n8n-1 n8n publish:workflow --id=tokenwiseusagesummary
docker restart tokenwise-n8n-1
```

Only one workflow (`tokenwiseskeleton`) should be active for `/webhook/tokenwise`.
Import deactivates the previous version automatically. The n8n named volume is
preserved.

The active webhook URL is:

```
http://localhost:5679/webhook/tokenwise
```

The read-only usage summary webhook is:

```
http://localhost:5679/webhook/tokenwise-usage-summary
```

It forwards `period_days`, `dept_id`, and the optional positive
`operating_cost_usd` ROI scenario to the optimizer service.

(When the workflow is NOT active you can still use the test URL
`http://localhost:5679/webhook-test/tokenwise`, but you must click
"Execute workflow" in the editor for each call. Activating is easier.)

## Test it directly (PowerShell)

```powershell
$body = @{ prompt = "How do I reset my password?"; policy_mode = "balanced" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:5679/webhook/tokenwise" -Method Post -Body $body -ContentType "application/json"
```

You should get back `{ answer, receipt }`.

## Notes / known skeleton limitations

- The HTTP nodes call the services by their docker-compose service names
  (e.g. `http://guardrails-service:8000`). This only resolves **inside** the
  docker network, which is correct because n8n runs in the same compose stack.
- CORS: the Webhook node sets `allowedOrigins: *` and the Respond node adds an
  `Access-Control-Allow-Origin: *` header so the React dev server can call it
  from the browser.
- Provider execution calls `POST http://optimizer-service:8000/providers/execute`
  (real Ollama local model; optional OpenAI when configured). There is no Mock
  Model fallback node.
