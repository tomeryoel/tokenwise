# TokenWise

**Real-Time LLM Cost Optimization Gateway.**

TokenWise is a middleware layer that sits between applications/users and LLM
providers. Every AI request passes through TokenWise, which optimizes it before
it reaches a model (guardrails, semantic cache, dynamic routing, compression),
then reports the savings.

> **Status:** four-layer end-to-end path is working. **Guardrails (Day 3)**,
> **semantic cache (Day 4)**, **LangGraph optimizer (Day 5)**, **Layer 4
> provider execution (Day 6)**, and **usage DB + Dashboard metrics (Day 7)** are
> now real. PyTorch training and Langfuse tracing remain for later phases.

## Architecture (four layers)

```mermaid
flowchart TB
    subgraph L1 [Layer 1 - UI]
        UI["React + Vite + TypeScript"]
    end
    subgraph L2 [Layer 2 - Orchestration]
        N8N["n8n workflow"]
    end
    subgraph L3 [Layer 3 - FastAPI microservices]
        GR["guardrails-service :8001"]
        RAG["rag-cache-service :8002"]
        IMG["image-analyser-service :8003"]
        OPT["optimizer-service :8004"]
    end
    subgraph L4 [Layer 4 - Model provider]
        OLLAMA["Ollama local"]
        OPENAI["OpenAI optional"]
    end

    UI -->|POST webhook| N8N
    N8N --> GR
    N8N --> RAG
    N8N --> OPT
    N8N -. later .-> IMG
    OPT --> OLLAMA
    OPT -. when configured .-> OPENAI
    N8N -->|answer + Decision Receipt| UI
```

See [docs/architecture.md](docs/architecture.md) for details and
[contracts/api-contracts.md](contracts/api-contracts.md) for the API shapes.

## Repository layout

```
tokenwise/
  docker-compose.yml          # runs everything
  README.md
  docs/architecture.md        # diagrams + what is real vs mocked
  contracts/api-contracts.md  # API contracts (v0)
  services/
    guardrails-service/       # FastAPI: /health /check/input /check/output
    rag-cache-service/        # FastAPI: /health /cache/lookup /cache/store /policy/query
    image-analyser-service/   # FastAPI: /health /analyse
    optimizer-service/        # FastAPI: /health /agent/run /providers/* /usage/*
  n8n/
    tokenwise-skeleton.workflow.json  # import into n8n
    README.md                          # n8n setup instructions
  frontend/                   # React + Vite + TypeScript (Playground/Dashboard/Admin)
```

## Prerequisites (Windows)

- Docker Desktop (running)
- That's it for the docker path. (Node.js only needed if you run the frontend
  outside Docker.)

## Run everything (PowerShell)

From the repository root:

```powershell
docker compose up --build
```

This starts:

| Component | URL |
|---|---|
| React UI | http://localhost:5173 |
| n8n | http://localhost:5679 |
| guardrails-service | http://localhost:8001/health |
| rag-cache-service | http://localhost:8002/health |
| image-analyser-service | http://localhost:8003/health |
| optimizer-service | http://localhost:8004/health |

Then import + activate the n8n workflow (one-time) as described in
[n8n/README.md](n8n/README.md).

## Test it

### 1. Health checks (PowerShell)

```powershell
Invoke-RestMethod http://localhost:8001/health
Invoke-RestMethod http://localhost:8002/health
Invoke-RestMethod http://localhost:8003/health
Invoke-RestMethod http://localhost:8004/health
```

Each returns `{"status":"ok","service":"..."}`.

### 2. End-to-end through n8n (PowerShell)

```powershell
$body = @{ prompt = "How do I reset my password?"; policy_mode = "balanced" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://localhost:5679/webhook/tokenwise" -Method Post -Body $body -ContentType "application/json"
```

> Note: n8n is published on host port **5679** (not the default 5678) so it does
> not collide with any other n8n you may already run on this machine. Inside the
> compose network n8n still listens on 5678.

Returns `{ answer, receipt }` where `receipt` contains `guardrail_status`,
`cache_status`, `selected_tier`, `estimated_tokens`, `estimated_cost`,
`optimization_reason`, `cost_saved`.

### 3. From the UI

Open http://localhost:5173, type a prompt in **Playground**, pick a policy mode,
click **Run with TokenWise**, and read the answer + Decision Receipt.

> If the n8n workflow is not imported/active yet, the UI shows a clearly-labelled
> "temporary local mock" banner so it is still demonstrable. Import + activate the
> workflow to exercise the real Layer 2 -> Layer 3 path.

## Semantic cache (Day 4)

The `rag-cache-service` is a **real** semantic cache:

- Embeddings: `sentence-transformers/all-MiniLM-L6-v2` (CPU only).
- Store: ChromaDB persistent client at `/app/data/chroma` on the `rag_cache_data`
  volume; the HF model is cached at `/app/data/hf` on the same volume so it is not
  re-downloaded on every restart. **Cache entries survive container restarts.**
- Similarity: cosine, `confidence = clamp(1 - cosine_distance, 0, 1)`; default
  threshold `0.88` (env `CACHE_SIMILARITY_THRESHOLD`, overridable per request).
- Department isolation: lookups filter by `dept_id` metadata (default `demo-support`).
- Sensitive requests (`contains_sensitive_data=true`, e.g. PII) are never searched
  or stored.

On a cache hit, n8n **skips the optimizer and mock model**, runs the cached answer
through the output guardrail, and returns it with `savings_source=semantic_cache`.
On a miss, the model path runs and the safe final answer is stored (best-effort).

> First lookup/store after a cold start downloads the MiniLM model (~90 MB) into
> the volume; subsequent restarts reuse it.

## Optimizer LangGraph (Day 5)

The `optimizer-service` is a real, deterministic, **conditional** **LangGraph**
state graph (`services/optimizer-service/graph.py`). A router
(`route_request_path`) uses conditional edges to pick one of five paths -
`reject_path`, `cache_path`, `local_only_path`, `vision_path`,
`standard_optimization_path` - and the standard path has a second conditional edge
(`should_recommend_compression`) that runs the compression node only when needed.
All paths converge into cost estimation + final plan.

It returns a structured Optimization Plan (routing tier, compression
recommendation, fallback plan, cost/savings estimate, decision reasons) plus graph
observability (`graph_path`, `branch_reason`, `executed_nodes`). Policy modes
(`conservative`/`balanced`/`aggressive`) can produce different plans for the same
prompt. See [docs/architecture.md](docs/architecture.md) for the graph diagram and
the command to print the compiled graph as Mermaid.

Run the optimizer unit tests without Docker/n8n:

```powershell
cd services/optimizer-service
pip install -r requirements.txt pytest
python -m pytest -q
```

## Layer 4 model execution (Day 6)

The optimizer-service now executes real models via `POST /providers/execute`.
Provider adapters live in `services/optimizer-service/providers/` as an MVP
packaging decision (four-service architecture preserved).

- **Ollama (local):** `POST {OLLAMA_BASE_URL}/api/chat` with `stream=false`.
  Default model: `llama3.1:latest` (detected on host). Docker uses
  `http://host.docker.internal:11434` via `extra_hosts`.
- **OpenAI (optional):** Responses API, enabled only when
  `ENABLE_OPENAI_PROVIDER=true` and `OPENAI_API_KEY` is set. Disabled safely
  when not configured.
- **Never commit API keys.** Use `services/optimizer-service/.env.example` as
  a template only.

Provider health: `GET http://localhost:8004/providers/health`

## Usage database and Dashboard (Day 7)

The optimizer-service persists terminal request outcomes in SQLite at
`/app/data/usage/tokenwise.db` (Docker volume `usage_data`).

- `POST /usage/log` — idempotent request logging (n8n calls on every terminal path)
- `GET /usage/summary` — aggregated metrics for the Dashboard
- `GET /usage/recent` — privacy-safe recent request list (no prompts)

Dashboard fetches analytics via n8n read-only webhook:
`GET http://localhost:5679/webhook/tokenwise-usage-summary`

**Primary savings metric:** `actual_cost_saved` when known, else `estimated_savings`
(one value per request — never double-counted).

**ROI:** `savings_percentage` vs baseline is reported; true commercial ROI is not
claimed (`roi_status: operating_cost_not_modeled`) because TokenWise operating
cost is not yet modeled.

**Privacy:** only SHA-256 prompt fingerprints stored; no raw prompts, PII, or secrets.

Development reset (optional): `python -m usage.reset_db --force`

## What is still mocked

- Image analyser returns a fixed class; not wired into the flow yet.
- Langfuse is a commented placeholder in docker-compose.
- Prompt compression is recommended only (not executed).

Real: guardrails (Day 3), semantic cache (Day 4), LangGraph optimizer (Day 5),
Layer 4 provider execution (Day 6), usage DB + Dashboard (Day 7).

## Frontend without Docker (optional)

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```
