# Cursor Connector

MomiHelm can ingest **Cursor composer history** from the local Cursor
`state.vscdb` database and turn it into coding sessions, attempts, and
connector-sourced context for the Dashboard.

This is the Cursor integration for MomiHelm. It includes:

1. **Historical ingest** from local Cursor `state.vscdb`
2. **Model catalog + offline/online routing** across Cursor LLMs
3. **Live advisory routing** inside Cursor via MCP tools + hooks

It does **not** yet:

- forcibly switch the selected Cursor model for you
- verify code changes through CI automatically
- observe every Cursor keystroke in real time beyond prompt-submit hooks

## Architecture

```text
Cursor IDE
  |-- hooks (sessionStart / beforeSubmitPrompt)
  |-- MCP tools (recommend / list / compare)
  |-- local state.vscdb sync CLI
        |
        v
MomiHelm gateway + optimizer
        |
        v
Dashboard / Model Fit / Cost-to-Success
```

The connector runs **on your Mac**, not inside Docker, because Cursor stores its
database on the host filesystem.

## Setup

1. Start MomiHelm locally:

```bash
./momihelm start
```

2. Create the owner account in the UI if this is first run.

3. Add connector settings to `.env`:

```env
MOMIHELM_CONNECTOR_TOKEN=replace-with-a-long-random-token
MOMIHELM_CONNECTOR_USER_EMAIL=your-owner-email@example.com
MOMIHELM_GATEWAY_URL=http://127.0.0.1:5173
```

4. Restart MomiHelm so the gateway picks up the new env vars:

```bash
./momihelm stop
./momihelm start
```

## Dry run (inspect local Cursor data)

```bash
PYTHONPATH=. python3 -m connectors.cursor sync --dry-run
```

This reads:

- `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`
- workspace copies under `~/Library/Application Support/Cursor/User/workspaceStorage/*/state.vscdb`

## Sync into MomiHelm

```bash
./momihelm cursor-sync
```

Or directly:

```bash
PYTHONPATH=. python3 -m connectors.cursor sync
```

Then open the Dashboard and look for sessions whose attempts have
`context_source=connector`.

## Cursor model routing

MomiHelm now maintains a catalog of Cursor-visible models:

- Auto
- Composer 2.5
- GPT-5.6 Sol
- GPT-5.6 Terra
- Sonnet 5
- Cursor Grok 4.5
- Fable 5
- Opus 5

APIs:

```bash
curl -b cookies.txt http://127.0.0.1:5173/api/cursor/models
curl -b cookies.txt -X POST http://127.0.0.1:5173/api/cursor/route/recommend \
  -H 'Content-Type: application/json' \
  -d '{
    "objective": "Fix a flaky unit test in auth middleware.",
    "task_type": "bug_fix",
    "complexity_level": "medium",
    "workflow": "agent"
  }'
```

During `./momihelm cursor-sync`, each imported Cursor attempt stores:

- normalized executed Cursor model
- MomiHelm recommended tier/model for the same objective
- enough metadata for Model Fit and Cost-to-Success on the Dashboard

Routing during sync is **advisory**. MomiHelm does not switch the model
inside Cursor automatically.

## Live routing inside Cursor (this slice)

### MCP server

Project config: `.cursor/mcp.json`

Tools:

- `momihelm_list_models`
- `momihelm_recommend_model`
- `momihelm_compare_models`

After opening this repo in Cursor, enable the **momihelm-cursor** MCP server
if Cursor asks. Then ask the agent:

> Use momihelm_recommend_model for this task: fix a flaky auth unit test

### Hooks

Project hooks (`.cursor/hooks.json`):

- `sessionStart` injects MomiHelm routing guidance into the conversation context
- `beforeSubmitPrompt` computes a recommendation and writes it to
  `.momihelm/last-route.json` (fail-open; never blocks your prompt)

### Offline CLI

No Docker required:

```bash
./momihelm cursor-recommend "Fix a flaky unit test in auth middleware."
./momihelm cursor-recommend "Design a multi-region payment failover" --json
```

### Cursor rule

`.cursor/rules/momihelm-model-routing.mdc` tells the agent to request a
recommendation before heavy coding work.

## Privacy

- Raw Cursor chat text is used locally to classify the session objective.
- MomiHelm stores only a **SHA-256 fingerprint** of the objective in SQLite.
- Assistant-turn token counts and model names are stored as attempt metadata.

## EC2 / web deployment note

You can deploy MomiHelm to AWS EC2 with `./momihelm web-start`, but the Cursor
connector still runs on the machine where Cursor IDE is installed. For EC2-only
deployments, use Playground/manual sessions or a future live Cursor hook instead
of local `state.vscdb` sync.

See [docs/web-deployment.md](web-deployment.md).

## Cursor Agent through MomiHelm (experimental)

See [cursor-agent-bridge.md](cursor-agent-bridge.md) for the official Cursor SDK
bridge that lets users run Cursor Agent tasks from the MomiHelm web app.

## Next slices

1. Harden Cursor SDK bridge + verified model selection UX
2. Automated verification events from tests/build output
3. Personal / team / department insights on Cursor-through-MomiHelm sessions
