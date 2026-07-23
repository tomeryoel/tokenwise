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
2. calculates and persists a digest of their contents,
3. exits without touching the database when the files are unchanged,
4. refuses changed imports if a running n8n process is detected,
5. otherwise imports them with their stable IDs and publishes the current
   versions, and
6. exits successfully before n8n starts.

The stable workflow IDs are:

- Gateway: `tokenwiseskeleton`
- Usage summary: `tokenwiseusagesummary`

The production webhook URLs are private Docker-network endpoints:

```text
http://n8n:5678/webhook/tokenwise
http://n8n:5678/webhook/tokenwise-usage-summary
```

The React frontend proxies same-origin `/api` calls to `gateway-service`.
The gateway authenticates the session and injects trusted organization, user,
department, and policy fields before it calls n8n. n8n is not published to the
host.

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

The start command stops n8n before bootstrap updates its SQLite database. The
bootstrap guard also rejects changed imports if n8n is reachable, preventing an
advanced Compose command from silently removing live webhook registrations.

## Re-import after workflow development

The normal `start` command re-imports and publishes committed workflow changes.
For an explicit recovery cycle:

```bash
docker compose stop frontend gateway-service n8n
docker compose run --rm --no-deps n8n-init
docker compose up -d n8n gateway-service frontend
```

The same commands work in PowerShell. The named `n8n_data` volume is preserved.
The importer uses stable IDs, so it updates the intended workflows rather than
creating a second production webhook path.

The bootstrap lifecycle regression test can be run without Docker:

```bash
./n8n/test_bootstrap.sh
```

## Direct webhook test

Direct n8n testing is limited to one-off containers on the private Compose
network. It is intended for release diagnostics and must supply an explicit
test identity:

```bash
docker compose run --rm --no-deps release-smoke
```

For a single manual diagnostic:

```bash
docker compose run --rm --no-deps release-smoke python -c \
  "import json,urllib.request; p=json.dumps({'prompt':'Hello','organization_id':'manual-test','user_id':'manual-test','dept_id':'manual-test','policy_mode':'balanced'}).encode(); print(urllib.request.urlopen(urllib.request.Request('http://n8n:5678/webhook/tokenwise',data=p,headers={'Content-Type':'application/json'})).read().decode())"
```

The response contains `{ answer, receipt }`.

## Operational notes

- n8n is pinned through `N8N_VERSION` in `.env`; do not switch to `latest`
  without rerunning the full release smoke test.
- HTTP nodes use Docker service names such as
  `http://guardrails-service:8000`; those names resolve only inside the Compose
  network by design.
- New execution payload retention is disabled. Automatic pruning remains off so
  existing history is not deleted without explicit approval.
- Provider execution calls the real optimizer provider endpoint. There is no
  mock-answer fallback.
- `n8n-init` is expected to show `Exited (0)` after startup because it is a
  successful one-shot service.
