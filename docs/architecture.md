# TokenWise - Architecture (Walking Skeleton, Day 1-2)

TokenWise is a real-time LLM cost-optimization gateway. Every AI request passes
through TokenWise, which optimizes it before it reaches a model, then reports the
savings. This document shows the four-layer architecture that the Day 1-2 walking
skeleton wires together end-to-end (with mocked logic inside each layer).

## Four-layer architecture

```mermaid
flowchart TB
    subgraph L1 [Layer 1 - User Interface]
        UI["React + Vite + TypeScript
        Playground / Dashboard / Admin"]
    end

    subgraph L2 [Layer 2 - Orchestration]
        N8N["n8n Workflow
        Webhook -> Normalize -> HTTP calls -> Respond"]
    end

    subgraph L3 [Layer 3 - FastAPI Microservices]
        GR["guardrails-service
        /check/input /check/output"]
        RAG["rag-cache-service
        /cache/lookup /cache/store /policy/query"]
        IMG["image-analyser-service
        /analyse"]
        OPT["optimizer-service
        /agent/run"]
    end

    subgraph L4 [Layer 4 - Model Providers]
        MOCK["Mock model response
        (real Ollama / external LLMs later)"]
    end

    subgraph X [Cross-cutting - placeholder only]
        LF["Langfuse (not implemented yet)"]
    end

    UI -->|"POST webhook (prompt, policy_mode)"| N8N
    N8N --> GR
    N8N --> RAG
    N8N --> OPT
    N8N -. "only when file attached (later)" .-> IMG
    N8N --> MOCK
    N8N -->|"answer + Decision Receipt"| UI
    N8N -. "traces (later)" .-> LF
```

## Request flow (with real guardrails + semantic cache)

```mermaid
sequenceDiagram
    participant UI as React UI
    participant N as n8n
    participant G as guardrails-service
    participant C as rag-cache-service
    participant O as optimizer-service

    UI->>N: POST /webhook/tokenwise {prompt, policy_mode, dept_id}
    N->>N: Normalize request
    N->>G: POST /check/input
    alt input blocked
        G-->>N: {pass:false, reason}
        N-->>UI: blocked answer + receipt (short-circuit)
    else input passed
        N->>C: POST /cache/lookup (dept_id filtered)
        alt cache hit (confidence >= threshold)
            C-->>N: {hit:true, confidence, answer, entry_id}
            N->>G: POST /check/output (cached answer)
            N-->>UI: cached answer + receipt (savings_source=semantic_cache)
        else cache miss
            C-->>N: {hit:false, confidence}
            N->>O: POST /agent/run
            O-->>N: {selected_tier, tokens, cost, cost_saved}
            N->>N: Mock model answer
            N->>G: POST /check/output (model answer)
            N->>C: POST /cache/store (best-effort, safe answer)
            N-->>UI: answer + receipt (savings_source=model_routing)
        end
    end
```

## What is real vs mocked in this step

| Layer / concern | Status in skeleton |
|---|---|
| React UI (Playground/Dashboard/Admin) | Real (minimal) |
| n8n orchestration workflow | Real wiring, mock logic |
| 4 FastAPI services + /health | Real services, mock responses |
| Guardrails logic | Real (Day 3: rules + regex, input & output) |
| Semantic cache / embeddings | Real (Day 4: MiniLM + ChromaDB, cosine, dept isolation) |
| LangGraph optimizer decision | Mocked (static plan) |
| PyTorch image analysis | Mocked (static class) |
| Model provider call | Mocked answer string |
| Langfuse tracing | Placeholder only |
| Usage DB / ROI | Not yet (Dashboard uses mock numbers) |
