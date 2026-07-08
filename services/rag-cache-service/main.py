"""rag-cache-service (walking skeleton).

Day 1-2: mock responses only. Real semantic cache (sentence-transformers +
ChromaDB, similarity threshold, confidence, dept isolation) and policy retrieval
come later.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

SERVICE_NAME = "rag-cache-service"

app = FastAPI(title=SERVICE_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CacheLookupRequest(BaseModel):
    prompt: str = ""
    dept_id: str = "demo"
    task_type: str = "general"


class CacheStoreRequest(BaseModel):
    prompt: str = ""
    answer: str = ""
    dept_id: str = "demo"


class PolicyQueryRequest(BaseModel):
    prompt: str = ""
    k: int = 3


@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/cache/lookup")
def cache_lookup(req: CacheLookupRequest):
    # MOCK: always a cache miss. Real embedding similarity lookup comes later.
    return {"cache_status": "miss", "confidence": 0.0, "answer": None}


@app.post("/cache/store")
def cache_store(req: CacheStoreRequest):
    # MOCK: pretend to store.
    return {"stored": True}


@app.post("/policy/query")
def policy_query(req: PolicyQueryRequest):
    # MOCK: no retrieved policies yet.
    return {"policies": []}
