"""Configuration for the MomiHelm offline Ragas evaluation.

All values are environment-overridable so the experiment is reproducible on a new
machine. Defaults target a fully local run (Ollama judge + local HF embeddings)
with no external API calls and no secrets.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


def _env(name: str, default: str) -> str:
    val = os.environ.get(name)
    return val if val not in (None, "") else default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except (TypeError, ValueError):
        return default


def new_run_id(mode: str) -> str:
    """Unique, sortable run id: <UTC timestamp>-<mode>-<short uuid>."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}-{mode}-{uuid.uuid4().hex[:8]}"


def eval_department(run_id: str) -> str:
    """Dedicated evaluation department to avoid Usage Dashboard contamination
    and stale semantic-cache contamination across runs."""
    return f"ragas-eval-{run_id}"


@dataclass
class QualityWeights:
    """Composite quality weights (must be renormalized when metrics are missing)."""

    semantic_similarity: float = 0.35
    response_relevancy: float = 0.25
    factual_correctness: float = 0.25
    tokenwise_rubric: float = 0.15

    def as_map(self) -> dict[str, float]:
        return {
            "semantic_similarity": self.semantic_similarity,
            "response_relevancy": self.response_relevancy,
            "factual_correctness": self.factual_correctness,
            "tokenwise_rubric": self.tokenwise_rubric,
        }


@dataclass
class EvalConfig:
    # --- run identity ---
    mode: str = "smoke"
    run_id: str = ""
    department: str = ""

    # --- judge (LLM evaluator) ---
    judge_provider: str = field(default_factory=lambda: _env("RAGAS_JUDGE_PROVIDER", "ollama"))
    judge_model: str = field(default_factory=lambda: _env("RAGAS_JUDGE_MODEL", "llama3.1:latest"))
    ollama_base_url: str = field(
        default_factory=lambda: _env("RAGAS_OLLAMA_BASE_URL", "http://localhost:11434")
    )
    request_timeout_seconds: int = field(
        default_factory=lambda: _env_int("RAGAS_REQUEST_TIMEOUT_SECONDS", 180)
    )
    max_retries: int = field(default_factory=lambda: _env_int("RAGAS_MAX_RETRIES", 1))

    # --- optional external judge (disabled by default, never silently used) ---
    enable_openai_judge: bool = field(
        default_factory=lambda: _env("RAGAS_ENABLE_OPENAI_JUDGE", "false").lower() == "true"
    )

    # --- embeddings (local HF) ---
    embedding_model: str = field(
        default_factory=lambda: _env(
            "RAGAS_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
    )

    # --- baseline (direct, un-optimized) ---
    baseline_provider: str = field(default_factory=lambda: _env("TOKENWISE_BASELINE_PROVIDER", "ollama"))
    baseline_model: str = field(default_factory=lambda: _env("TOKENWISE_BASELINE_MODEL", "llama3.1:latest"))

    # --- MomiHelm optimized path ---
    webhook_url: str = field(
        default_factory=lambda: _env(
            "TOKENWISE_WEBHOOK_URL", "http://localhost:5679/webhook/tokenwise"
        )
    )
    n8n_health_url: str = field(
        default_factory=lambda: _env("TOKENWISE_N8N_HEALTH_URL", "http://localhost:5679/healthz")
    )
    optimizer_health_url: str = field(
        default_factory=lambda: _env(
            "TOKENWISE_OPTIMIZER_HEALTH_URL", "http://localhost:8004/providers/health"
        )
    )
    policy_mode: str = field(default_factory=lambda: _env("TOKENWISE_POLICY_MODE", "balanced"))

    # --- modeled cost (USD / 1k tokens); actual Ollama API cost is 0 ---
    premium_price_per_1k: float = field(
        default_factory=lambda: _env_float("TOKENWISE_PREMIUM_PRICE_PER_1K", 0.03)
    )

    # --- quality gate ---
    quality_gate_ratio: float = field(
        default_factory=lambda: _env_float("RAGAS_QUALITY_GATE_RATIO", 0.90)
    )
    quality_critical_min: float = field(
        default_factory=lambda: _env_float("RAGAS_QUALITY_CRITICAL_MIN", 0.60)
    )
    rubric_scale_max: float = 5.0

    weights: QualityWeights = field(default_factory=QualityWeights)

    # --- concurrency (keep low to protect local Ollama) ---
    max_concurrency: int = field(default_factory=lambda: _env_int("RAGAS_MAX_CONCURRENCY", 1))

    def openai_compat_base_url(self) -> str:
        base = self.ollama_base_url.rstrip("/")
        return base if base.endswith("/v1") else base + "/v1"

    def to_public_dict(self) -> dict:
        """Serializable config with no secrets (there are none by design)."""
        d = asdict(self)
        return d
