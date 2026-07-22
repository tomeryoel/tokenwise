"""Real Ragas 0.4.x metric wiring (collections API + custom rubric).

Ragas 0.4.3 deprecates the legacy ``from ragas import evaluate`` batch API in
favour of the collections-based metrics (``ragas.metrics.collections``) invoked
with ``.ascore(...)`` returning a ``MetricResult``, plus custom ``DiscreteMetric``/
``NumericMetric`` rubrics scored via ``.ascore(llm=..., **vars)``.

Judge  : local Ollama through its OpenAI-compatible endpoint + ``llm_factory``.
Embeds : local HuggingFace ``all-MiniLM-L6-v2`` (CPU), no external API.
"""
from __future__ import annotations

import asyncio
import importlib
from typing import Any, Optional

from .config import EvalConfig
from .schemas import MetricScore

EXPECTED_RAGAS_MAJOR_MINOR = (0, 4)

# Metric names (stable identifiers used across artifacts).
M_SEMANTIC = "semantic_similarity"
M_RELEVANCY = "response_relevancy"
M_FACTUAL = "factual_correctness"
M_RUBRIC = "tokenwise_rubric"


class RagasCompatibilityError(RuntimeError):
    """Raised when the installed Ragas version/API does not match expectations."""


def ragas_version() -> str:
    import ragas
    return getattr(ragas, "__version__", "unknown")


def assert_ragas_api() -> str:
    """Fail loudly if the pinned collections-based API is unavailable.

    This guards against silently running against an incompatible Ragas version
    or the deprecated ``evaluate``-only API.
    """
    ver = ragas_version()
    parts = ver.split(".")
    try:
        major, minor = int(parts[0]), int(parts[1])
    except (IndexError, ValueError) as exc:
        raise RagasCompatibilityError(f"cannot parse ragas version '{ver}'") from exc

    if (major, minor) < EXPECTED_RAGAS_MAJOR_MINOR:
        raise RagasCompatibilityError(
            f"ragas {ver} is older than the expected collections API "
            f"({EXPECTED_RAGAS_MAJOR_MINOR[0]}.{EXPECTED_RAGAS_MAJOR_MINOR[1]}.x). "
            "The deprecated evaluate()-only API is not supported by this runner."
        )

    # Required symbols for the collections-based experiment API.
    try:
        collections = importlib.import_module("ragas.metrics.collections")
        for cls in ("SemanticSimilarity", "FactualCorrectness", "AnswerRelevancy",
                    "DomainSpecificRubrics"):
            if not hasattr(collections, cls):
                raise RagasCompatibilityError(
                    f"ragas.metrics.collections.{cls} is unavailable in ragas {ver}"
                )
        llms = importlib.import_module("ragas.llms")
        if not hasattr(llms, "llm_factory"):
            raise RagasCompatibilityError(f"ragas.llms.llm_factory missing in ragas {ver}")
        experiment_mod = importlib.import_module("ragas")
        for sym in ("experiment", "Dataset"):
            if not hasattr(experiment_mod, sym):
                raise RagasCompatibilityError(f"ragas.{sym} missing in ragas {ver}")
        embeddings = importlib.import_module("ragas.embeddings")
        if not hasattr(embeddings, "HuggingFaceEmbeddings"):
            raise RagasCompatibilityError(
                f"ragas.embeddings.HuggingFaceEmbeddings missing in ragas {ver}"
            )
    except ImportError as exc:
        raise RagasCompatibilityError(f"ragas API import failed for {ver}: {exc}") from exc
    return ver


# Custom MomiHelm grounding rubric (1-5) implemented with the Ragas collections
# DomainSpecificRubrics metric (robust instructor path). Penalizes unsupported claims.
TOKENWISE_RUBRICS = {
    "score1_description": (
        "The response is irrelevant to the question, contradicts the reference, or is "
        "unusable."
    ),
    "score2_description": (
        "The response is weakly relevant OR makes unsupported claims about MomiHelm "
        "capabilities that are NOT in the reference (e.g. real-time load optimization, "
        "autoscaling, learned routing, live provider-quality ranking, automatic "
        "company-policy ingestion, or real Policy RAG enforcement)."
    ),
    "score3_description": (
        "The response is generally relevant and mostly consistent with the reference but is "
        "vague, incomplete, or partially conflates implemented and planned features."
    ),
    "score4_description": (
        "The response is relevant, consistent with the reference, and avoids unsupported "
        "claims, with only minor omissions or wording issues."
    ),
    "score5_description": (
        "The response directly answers the question, follows the instruction, is fully "
        "consistent with the reference, correctly distinguishes implemented vs planned "
        "MomiHelm features, makes no unsupported capability claims, and is concise and clear."
    ),
}


class MetricEngine:
    """Builds and runs real Ragas metrics with a local judge + local embeddings."""

    def __init__(self, cfg: EvalConfig):
        self.cfg = cfg
        self._llm = None
        self._embeddings = None
        self._semantic = None
        self._relevancy = None
        self._factual = None
        self._rubric = None
        self.judge_calls = 0
        self.embedding_calls = 0

    # -- lazy builders -------------------------------------------------------
    def _build_llm(self):
        if self._llm is not None:
            return self._llm
        from openai import AsyncOpenAI
        from ragas.llms import llm_factory

        if self.cfg.judge_provider != "ollama":
            raise RagasCompatibilityError(
                f"only the local 'ollama' judge is enabled by default; "
                f"got provider '{self.cfg.judge_provider}'"
            )
        client = AsyncOpenAI(
            base_url=self.cfg.openai_compat_base_url(),
            api_key="ollama",  # Ollama ignores the key; not a secret.
            max_retries=self.cfg.max_retries,
            timeout=float(self.cfg.request_timeout_seconds),
        )
        self._llm = llm_factory(self.cfg.judge_model, provider="openai", client=client)
        return self._llm

    def _build_embeddings(self):
        if self._embeddings is not None:
            return self._embeddings
        from ragas.embeddings import HuggingFaceEmbeddings

        self._embeddings = HuggingFaceEmbeddings(
            model=self.cfg.embedding_model,
            use_api=False,
            normalize_embeddings=True,
        )
        return self._embeddings

    def semantic(self):
        if self._semantic is None:
            from ragas.metrics.collections import SemanticSimilarity
            self._semantic = SemanticSimilarity(embeddings=self._build_embeddings())
        return self._semantic

    def relevancy(self):
        if self._relevancy is None:
            from ragas.metrics.collections import AnswerRelevancy
            self._relevancy = AnswerRelevancy(
                llm=self._build_llm(), embeddings=self._build_embeddings()
            )
        return self._relevancy

    def factual(self):
        if self._factual is None:
            from ragas.metrics.collections import FactualCorrectness
            self._factual = FactualCorrectness(llm=self._build_llm())
        return self._factual

    def rubric(self):
        if self._rubric is None:
            from ragas.metrics.collections import DomainSpecificRubrics
            self._rubric = DomainSpecificRubrics(
                llm=self._build_llm(),
                rubrics=TOKENWISE_RUBRICS,
                with_reference=True,
                name=M_RUBRIC,
            )
        return self._rubric

    # -- scoring (each returns a MetricScore; never raises) ------------------
    async def _bounded(self, coro, metric: str, variant: str) -> MetricScore:
        """Bound a metric call so a stuck local judge cannot hang the experiment."""
        timeout = float(self.cfg.request_timeout_seconds)
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            return MetricScore(
                metric, variant, status="error",
                error=f"TimeoutError: metric exceeded {timeout}s",
            )
        except Exception as exc:  # noqa: BLE001
            return MetricScore(metric, variant, status="error", error=_err(exc))

    async def score_semantic(self, variant: str, reference: str, response: str) -> MetricScore:
        if not reference or not response:
            return MetricScore(M_SEMANTIC, variant, status="not_applicable",
                               reason="missing reference or response")

        async def _run() -> MetricScore:
            self.embedding_calls += 1
            res = await self.semantic().ascore(reference=reference, response=response)
            return _result_to_score(M_SEMANTIC, variant, res)

        return await self._bounded(_run(), M_SEMANTIC, variant)

    async def score_relevancy(self, variant: str, user_input: str, response: str) -> MetricScore:
        if not user_input or not response:
            return MetricScore(M_RELEVANCY, variant, status="not_applicable",
                               reason="missing user_input or response")

        async def _run() -> MetricScore:
            self.judge_calls += 1
            self.embedding_calls += 1
            res = await self.relevancy().ascore(user_input=user_input, response=response)
            return _result_to_score(M_RELEVANCY, variant, res)

        return await self._bounded(_run(), M_RELEVANCY, variant)

    async def score_factual(self, variant: str, reference: str, response: str) -> MetricScore:
        if not reference or not response:
            return MetricScore(M_FACTUAL, variant, status="not_applicable",
                               reason="missing reference or response")

        async def _run() -> MetricScore:
            self.judge_calls += 1
            res = await self.factual().ascore(response=response, reference=reference)
            return _result_to_score(M_FACTUAL, variant, res)

        return await self._bounded(_run(), M_FACTUAL, variant)

    async def score_rubric(self, variant: str, user_input: str, reference: str,
                            response: str) -> MetricScore:
        if not response:
            return MetricScore(M_RUBRIC, variant, status="not_applicable",
                               reason="missing response")

        async def _run() -> MetricScore:
            self.judge_calls += 1
            res = await self.rubric().ascore(
                user_input=user_input,
                response=response,
                reference=reference or "(no reference provided)",
            )
            score = _result_to_score(M_RUBRIC, variant, res)
            # normalize 1-5 rubric to 0-1 for the composite while keeping raw value in reason
            if score.value is not None:
                raw = score.value
                score.reason = _append_reason(score.reason, f"raw_1_5={raw}")
                score.value = _clamp01((raw - 1.0) / (self.cfg.rubric_scale_max - 1.0))
            return score

        return await self._bounded(_run(), M_RUBRIC, variant)


def _result_to_score(metric: str, variant: str, res: Any) -> MetricScore:
    value = getattr(res, "value", None)
    reason = None
    to_dict = getattr(res, "to_dict", None)
    if callable(to_dict):
        try:
            d = to_dict()
            if isinstance(d, dict):
                reason = d.get("reason") or d.get("explanation")
        except Exception:  # noqa: BLE001
            reason = None
    try:
        num = float(value) if value is not None else None
    except (TypeError, ValueError):
        num = None
    if num is None:
        return MetricScore(metric, variant, status="error",
                           error=f"non-numeric metric value: {value!r}")
    return MetricScore(metric, variant, value=num, reason=reason, status="ok")


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _append_reason(existing: Optional[str], extra: str) -> str:
    if existing:
        return f"{existing} | {extra}"
    return extra


def _err(exc: Exception) -> str:
    name = type(exc).__name__
    msg = str(exc)
    if len(msg) > 240:
        msg = msg[:240] + "..."
    return f"{name}: {msg}" if msg else name
