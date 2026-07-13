"""rag-cache-service (Day 4: real MVP semantic cache).

Implements a real semantic cache using:
  * sentence-transformers/all-MiniLM-L6-v2 embeddings (CPU only)
  * ChromaDB persistent storage (embedded client, no separate server)
  * cosine similarity with a configurable threshold
  * dept_id metadata isolation
  * sensitive-data exclusion (never search or store sensitive requests)

Distance -> confidence:
  Chroma is configured with cosine space, so query() returns a cosine
  *distance* = 1 - cosine_similarity. We convert to a confidence/similarity
  score with:  confidence = clamp(1 - distance, 0.0, 1.0)
  A LARGER distance therefore means a LOWER confidence (never the reverse).

The /policy/query endpoint remains basic (no retrieval yet) - semantic cache
is the priority for Day 4.
"""
import os
import re
import time
import uuid

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import chromadb

SERVICE_NAME = "rag-cache-service"

CHROMA_DIR = os.environ.get("CHROMA_DIR", "/app/data/chroma")
DEFAULT_THRESHOLD = float(os.environ.get("CACHE_SIMILARITY_THRESHOLD", "0.88"))
EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
COLLECTION_NAME = "semantic_cache"

# Deterministic cost model shared with guardrails/optimizer: $0.03 / 1k tokens.
PREMIUM_PRICE_PER_TOKEN = 0.00003

app = FastAPI(title=SERVICE_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------- #
# Persistent Chroma client + lazily-loaded embedding model
# --------------------------------------------------------------------------- #
os.makedirs(CHROMA_DIR, exist_ok=True)
_chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
_collection = _chroma_client.get_or_create_collection(
    name=COLLECTION_NAME,
    metadata={"hnsw:space": "cosine"},
)

_model = None


def get_model():
    """Load all-MiniLM-L6-v2 once, on first use (keeps /health instant)."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(EMBED_MODEL_NAME, device="cpu")
    return _model


def normalize(text: str) -> str:
    """Light normalization: trim, collapse whitespace, lowercase."""
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def embed(text: str):
    vec = get_model().encode([normalize(text)], normalize_embeddings=True)[0]
    return vec.tolist()


def estimate_tokens(text: str) -> int:
    return round(len((text or "").split()) * 1.3)


def avoided_cost(tokens: int) -> float:
    return round(tokens * PREMIUM_PRICE_PER_TOKEN, 6)


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# --------------------------------------------------------------------------- #
# Request models (accept both `query` and legacy `prompt` for compatibility)
# --------------------------------------------------------------------------- #
class CacheLookupRequest(BaseModel):
    query: str | None = None
    prompt: str | None = None
    dept_id: str = "demo-support"
    task_type: str = "general"
    threshold: float | None = None
    contains_sensitive_data: bool = False


class CacheStoreRequest(BaseModel):
    query: str | None = None
    prompt: str | None = None
    answer: str = ""
    dept_id: str = "demo-support"
    task_type: str = "general"
    contains_sensitive_data: bool = False
    output_guardrail_passed: bool = True


class PolicyQueryRequest(BaseModel):
    prompt: str = ""
    k: int = 3


def _text(req) -> str:
    return (req.query or req.prompt or "").strip()


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/cache/lookup")
def cache_lookup(req: CacheLookupRequest):
    text = _text(req)
    dept_id = req.dept_id or "demo-support"
    threshold = req.threshold if req.threshold is not None else DEFAULT_THRESHOLD
    tokens = estimate_tokens(text)

    base = {
        "hit": False,
        "confidence": 0.0,
        "answer": None,
        "entry_id": None,
        "dept_id": dept_id,
        "estimated_tokens": tokens,
        "cost_saved": 0.0,
        "threshold": threshold,
    }

    # Sensitive requests are never searched in (or reused from) the cache.
    if req.contains_sensitive_data:
        return {**base, "reason": "sensitive_request_not_cacheable"}

    if text == "":
        return {**base, "reason": "empty_query"}

    results = _collection.query(
        query_embeddings=[embed(text)],
        n_results=1,
        where={"dept_id": dept_id},
    )

    ids = (results.get("ids") or [[]])[0]
    if not ids:
        return {**base, "reason": "no_entries_for_dept"}

    distance = (results.get("distances") or [[1.0]])[0][0]
    confidence = round(clamp01(1.0 - distance), 4)
    documents = (results.get("documents") or [[None]])[0]

    if confidence >= threshold:
        return {
            **base,
            "hit": True,
            "confidence": confidence,
            "answer": documents[0],
            "entry_id": ids[0],
            "cost_saved": avoided_cost(tokens),
            "reason": "semantic_cache_hit",
        }

    return {
        **base,
        "confidence": confidence,
        "reason": "below_similarity_threshold",
    }


@app.post("/cache/store")
def cache_store(req: CacheStoreRequest):
    text = _text(req)
    dept_id = req.dept_id or "demo-support"

    if req.contains_sensitive_data:
        return {"stored": False, "entry_id": None, "reason": "sensitive_not_cacheable"}
    if not req.output_guardrail_passed:
        return {"stored": False, "entry_id": None, "reason": "output_guardrail_failed"}
    if text == "":
        return {"stored": False, "entry_id": None, "reason": "empty_query"}
    if not (req.answer or "").strip():
        return {"stored": False, "entry_id": None, "reason": "empty_answer"}

    entry_id = uuid.uuid4().hex
    _collection.add(
        ids=[entry_id],
        embeddings=[embed(text)],
        documents=[req.answer],
        metadatas=[{
            "dept_id": dept_id,
            "task_type": req.task_type or "general",
            "query": text,
            "created_at": time.time(),
        }],
    )
    return {"stored": True, "entry_id": entry_id, "reason": "stored"}


@app.post("/policy/query")
def policy_query(req: PolicyQueryRequest):
    # Basic placeholder - real policy retrieval is a later stage.
    return {"policies": []}
