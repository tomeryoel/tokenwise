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

The active webhook URL is:

```
http://localhost:5679/webhook/tokenwise
```

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
