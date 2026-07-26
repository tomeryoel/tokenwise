# Cursor Agent through MomiHelm (experimental)

This slice proves the product loop:

```text
User → MomiHelm web app → local Cursor SDK bridge → Cursor SDK → MomiHelm → User
```

Correct claim for this prototype:

> MomiHelm can run Cursor Agent tasks through the official Cursor SDK and
> display the result inside the MomiHelm web application.

It does **not** claim that MomiHelm replaces Cursor IDE, controls Cursor chat,
or provides every Cursor surface.

## Components

| Piece | Role |
|---|---|
| `bridges/cursor-sdk/server.py` | Local-only FastAPI bridge using official `cursor-sdk` |
| Gateway `/api/cursor-agent/*` | Auth-gated proxy to the bridge + persistence |
| Optimizer `/connectors/cursor-sdk/runs` | Stores attempt metadata + result fingerprint |
| Playground mode **Cursor Agent (experimental)** | Model select/recommend + run + result display |

## Setup

1. Add to `.env` (never commit secrets):

```env
CURSOR_API_KEY=crsr_...
MOMIHELM_CURSOR_BRIDGE_TOKEN=replace-with-a-long-random-token
MOMIHELM_CURSOR_BRIDGE_URL=http://host.docker.internal:8787
MOMIHELM_CURSOR_BRIDGE_CWD=/absolute/path/to/your/repo
```

Use the same `MOMIHELM_CURSOR_BRIDGE_TOKEN` for the bridge process and for the
MomiHelm gateway (Docker Compose already forwards it).

2. Start MomiHelm:

```bash
./momihelm start
```

3. In a second terminal, start the bridge on the host:

```bash
./momihelm cursor-bridge
```

4. Open http://127.0.0.1:5173 → Playground → **Cursor Agent (experimental)**

5. Write a coding task, refresh recommendation, choose a model, click
   **Run with Cursor Agent**.

## What is persisted

- `provider=cursor-sdk`
- selected / recommended / used model
- SDK run id / agent id when available
- status, duration
- result **fingerprint** (not raw manager-visible transcript storage)
- coding session + attempt linkage for later Model Fit / verification

The authenticated caller still receives the result text in the API response so
it can be shown in the Playground.

## Security notes

- Bridge binds to `127.0.0.1` by default.
- Bridge requires `X-MomiHelm-Bridge-Token`.
- Gateway requires a normal MomiHelm login session.
- No writes to Cursor `state.vscdb`.
- `CURSOR_API_KEY` stays on the host bridge process.

## Limitations

- Experimental prototype only.
- Requires local bridge + Cursor API key.
- Not the same as driving the Cursor IDE Composer UI.
- Existing Ollama/OpenAI Playground paths remain unchanged.
- Advisory MCP/hooks/DB connector remain available and unchanged.
