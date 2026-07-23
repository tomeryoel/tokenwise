# MomiHelm n8n Operations

The gateway workflow implements Layer 2:

`Webhook -> Normalize -> Guardrails -> Cache/Image -> Optimizer -> Provider -> Output Guardrails -> Cache Store -> Usage Log -> Response`

Cache hits and blocked inputs short-circuit before provider execution. Image
attachments always use the image-aware local analysis path.

## Automatic bootstrap

Normal installation does not require opening the n8n editor or importing files
manually. `docker compose up` starts the one-shot `n8n-init` service before n8n.
It:

1. mounts both committed workflow JSON files read-only,
2. imports them with their stable IDs,
3. publishes the current versions, and
4. exits successfully before n8n starts.

The stable workflow IDs are:

- Gateway: `tokenwiseskeleton`
- Usage summary: `tokenwiseusagesummary`

The production webhook URLs remain:

```text
http://localhost:5679/webhook/tokenwise
http://localhost:5679/webhook/tokenwise-usage-summary
```

The React frontend uses an Nginx same-origin `/api` proxy, so browser requests
do not require permissive cross-origin access to n8n.

## Recommended lifecycle

macOS/Linux:

```bash
./momihelm start
./momihelm status
./momihelm smoke
```

Windows PowerShell:

```powershell
.\momihelm.ps1 start
.\momihelm.ps1 status
.\momihelm.ps1 smoke
```

The start command stops n8n before bootstrap updates its SQLite database. Never
run the importer concurrently with a running n8n process.

## Re-import after workflow development

The normal `start` command re-imports and publishes committed workflow changes.
For an explicit recovery cycle:

```bash
docker compose stop frontend n8n
docker compose run --rm --no-deps n8n-init
docker compose up -d n8n frontend
```

The same commands work in PowerShell. The named `n8n_data` volume is preserved.
The importer uses stable IDs, so it updates the intended workflows rather than
creating a second production webhook path.

## Optional editor access

n8n is available at http://127.0.0.1:5679. The first time you open its editor,
n8n may ask you to create a local owner account. This is optional for normal
MomiHelm usage because the workflows are already imported and published.

## Direct webhook test

PowerShell:

```powershell
$body = @{ prompt = "How do I reset my password?"; policy_mode = "balanced" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:5679/webhook/tokenwise" -Method Post -Body $body -ContentType "application/json"
```

macOS/Linux:

```bash
curl -fsS -X POST http://localhost:5679/webhook/tokenwise \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"How do I reset my password?","policy_mode":"balanced"}'
```

The response contains `{ answer, receipt }`.

## Operational notes

- n8n is pinned through `N8N_VERSION` in `.env`; do not switch to `latest`
  without rerunning the full release smoke test.
- HTTP nodes use Docker service names such as
  `http://guardrails-service:8000`; those names resolve only inside the Compose
  network by design.
- Provider execution calls the real optimizer provider endpoint. There is no
  mock-answer fallback.
- `n8n-init` is expected to show `Exited (0)` after startup because it is a
  successful one-shot service.
