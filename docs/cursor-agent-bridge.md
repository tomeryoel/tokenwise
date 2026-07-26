# Cursor Agent Coding Run through MomiHelm (experimental)

This slice proves the product loop:

```text
User → MomiHelm web app → local Cursor SDK bridge → Cursor SDK → local workspace → MomiHelm → User
```

Correct claim for this prototype:

> MomiHelm can run Cursor coding-agent tasks through the official Cursor SDK
> against a local workspace and display status, changed files, diff, and
> validation inside the MomiHelm web application.

It does **not** claim that MomiHelm replaces Cursor IDE, controls Cursor chat,
or fully sandboxes every terminal action the agent may take.

## Components

| Piece | Role |
|---|---|
| `bridges/cursor-sdk/server.py` | Local-only FastAPI bridge using official `cursor-sdk` |
| `bridges/cursor-sdk/workspace_safety.py` | Dirty-tree hard block, sandbox, allowlist, diff capture |
| Disposable sandbox | `bridges/cursor-sdk/workspaces/coding-sandbox` (from fixture) |
| Gateway `/api/cursor-agent/*` | Auth-gated proxy to the bridge + persistence |
| Optimizer `/connectors/cursor-sdk/runs` | Stores attempt metadata + fingerprints (not raw diffs) |
| Playground mode **Cursor Agent Coding Run (experimental)** | Model + validation + run + result/diff UI |

## Setup

1. Add to `.env` (never commit secrets):

```env
CURSOR_API_KEY=crsr_...
MOMIHELM_CURSOR_BRIDGE_TOKEN=replace-with-a-long-random-token
MOMIHELM_CURSOR_BRIDGE_URL=http://host.docker.internal:8787
# Optional override. Default is the disposable sandbox workspace.
# MOMIHELM_CURSOR_BRIDGE_CWD=/absolute/path/to/clean/git/repo
MOMIHELM_CURSOR_BRIDGE_SANDBOX=true
```

Use the same `MOMIHELM_CURSOR_BRIDGE_TOKEN` for the bridge process and for the
MomiHelm gateway (Docker Compose already forwards it).

2. Start MomiHelm:

```bash
./momihelm start
```

3. Optional bridge/SDK checks (does **not** affect `./momihelm doctor`):

```bash
./momihelm cursor-bridge-doctor
./momihelm cursor-sandbox-init
```

4. In a second terminal, start the bridge on the host:

```bash
./momihelm cursor-bridge
```

5. Open http://127.0.0.1:5173 → Playground → **Cursor Agent Coding Run (experimental)**

6. Write a coding task against the sandbox, refresh recommendation, choose a
   model, optionally choose an allowlisted validation command, click
   **Run Cursor Agent Coding Run**.

Reset the disposable sandbox when needed:

```bash
./momihelm cursor-sandbox-reset
```

## Safety constraints (this slice)

- Dirty Git worktree = **hard block** (no warn-and-continue).
- First real runs should use the **disposable sandbox**, not the main repo.
- No revert button in the UI.
- Raw full diffs are returned to the authenticated caller for the current run
  and are **not persisted by default**. Persistence stores relative changed
  paths + a diff fingerprint.
- Validation commands are allowlisted only:
  `npm test`, `npm run test`, `npm run lint`, `pytest`, `python -m pytest`.
- Official Cursor SDK only. No `state.vscdb` writes. No Cursor UI automation.
- `LocalAgentOptions.cwd` scopes the workspace. `SandboxOptions(enabled=...)`
  is passed when available. The SDK does **not** expose a rich command
  allowlist; do not claim full terminal/deletion enforcement beyond that.

## What is persisted

- `provider=cursor-sdk`
- selected / recommended / used model
- SDK run id / agent id when available
- status, duration
- result **fingerprint** (not raw manager-visible transcript storage)
- workspace kind, relative changed file paths, diff fingerprint
- validation command + status
- coding session + attempt linkage for later Model Fit / verification

The authenticated caller still receives result text and the per-run diff in the
API response so they can be shown in the Playground.

## Security notes

- Bridge binds to `127.0.0.1` by default.
- Bridge requires `X-MomiHelm-Bridge-Token`.
- Gateway requires a normal MomiHelm login session.
- No writes to Cursor `state.vscdb`.
- `CURSOR_API_KEY` stays on the host bridge process.
- `./momihelm doctor` remains independent of Cursor SDK / API key setup.

## Limitations and remaining risks

- Experimental prototype only.
- Requires local bridge + Cursor API key for real SDK execution.
- Agent terminal tools may still run inside the workspace/sandbox; SDK
  `SandboxOptions` is a boolean enable flag, not a full policy engine.
- Diff capture uses local `git status` / `git diff HEAD` after the run.
- Not the same as driving the Cursor IDE Composer UI.
- Existing Ollama/OpenAI Playground paths remain unchanged.
- Advisory MCP/hooks/DB connector remain available and unchanged.
