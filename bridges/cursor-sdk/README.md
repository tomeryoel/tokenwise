# Local MomiHelm Cursor SDK Bridge

This bridge must run on the developer machine (not inside Docker).
It uses the official Python `cursor-sdk` package for Cursor Agent Coding Runs.

## Setup

```bash
./momihelm cursor-bridge-doctor
./momihelm cursor-sandbox-init
export CURSOR_API_KEY=...
export MOMIHELM_CURSOR_BRIDGE_TOKEN=...
./momihelm cursor-bridge
```

## Endpoints (127.0.0.1 only by default)

- `GET  /health`
- `GET  /models`
- `POST /run`

Auth header:

```text
X-MomiHelm-Bridge-Token: <MOMIHELM_CURSOR_BRIDGE_TOKEN>
```

## Safety

- Dirty Git worktree hard-blocks `/run`
- Default workspace is the disposable sandbox under `workspaces/coding-sandbox`
- Validation commands are allowlisted
- Raw diffs are returned for the current response only (`persist_raw_diff=false`)

## Tests

```bash
cd bridges/cursor-sdk
.venv/bin/python -m pytest tests/test_workspace_safety.py -q
```
