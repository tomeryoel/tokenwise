"""Execution clients: honest direct baseline vs the real MomiHelm n8n pipeline.

- BaselineClient bypasses MomiHelm entirely (no guardrails, cache, LangGraph,
  fallback, savings): it calls Ollama directly with a fixed model.
- TokenWiseClient (legacy internal name) calls the real active MomiHelm webhook and parses the
  Decision Receipt.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import requests

from .config import EvalConfig
from .schemas import VariantExecution

# Decision Receipt fields we try to surface (all optional / parsed safely).
RECEIPT_FIELDS = [
    "guardrail_status", "output_guardrail_status", "cache_status", "cache_confidence",
    "cache_entry_id", "selected_tier", "provider", "model", "executed_tier",
    "task_type", "complexity_level", "complexity_score", "graph_path",
    "privacy_enforced", "prompt_redaction_applied", "actual_input_tokens",
    "actual_output_tokens", "actual_total_tokens", "actual_cost", "actual_cost_saved",
    "estimated_cost", "estimated_baseline_cost", "estimated_optimized_cost",
    "latency_ms", "used_fallback", "actual_execution_attempt_count", "savings_source",
    "savings_reason", "reason", "detected_risk_type", "provider_attempts",
    "executed_nodes", "decision_reasons",
]


def _modeled_baseline_cost(total_tokens: Optional[int], price_per_1k: float) -> Optional[float]:
    if total_tokens is None:
        return None
    return round((total_tokens / 1000.0) * price_per_1k, 6)


class BaselineClient:
    """Direct Ollama call (native /api/chat) — the un-optimized baseline."""

    def __init__(self, cfg: EvalConfig):
        self.cfg = cfg
        self.url = cfg.ollama_base_url.rstrip("/") + "/api/chat"

    def generate(self, prompt: str) -> VariantExecution:
        payload = {
            "model": self.cfg.baseline_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        started = time.perf_counter()
        try:
            resp = requests.post(self.url, json=payload,
                                 timeout=self.cfg.request_timeout_seconds)
            latency_ms = (time.perf_counter() - started) * 1000.0
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 - record, do not crash the run
            latency_ms = (time.perf_counter() - started) * 1000.0
            return VariantExecution(
                variant="baseline",
                provider=self.cfg.baseline_provider,
                model=self.cfg.baseline_model,
                latency_ms=round(latency_ms, 2),
                actual_cost=0.0,
                error=_safe_error(exc),
            )

        answer = ((data.get("message") or {}).get("content") or "").strip()
        in_tok = data.get("prompt_eval_count")
        out_tok = data.get("eval_count")
        total = None
        if isinstance(in_tok, int) or isinstance(out_tok, int):
            total = (in_tok or 0) + (out_tok or 0)
        return VariantExecution(
            variant="baseline",
            provider=self.cfg.baseline_provider,
            model=data.get("model") or self.cfg.baseline_model,
            answer=answer,
            input_tokens=in_tok,
            output_tokens=out_tok,
            total_tokens=total,
            latency_ms=round(latency_ms, 2),
            actual_cost=0.0,  # local Ollama: zero API cost (infra cost not modeled)
            modeled_baseline_cost=_modeled_baseline_cost(total, self.cfg.premium_price_per_1k),
            error=None if answer else "empty_answer",
        )


class TokenWiseClient:
    """Calls the real n8n webhook (the full optimized pipeline)."""

    def __init__(self, cfg: EvalConfig):
        self.cfg = cfg

    def run(self, prompt: str, department: str, policy_mode: Optional[str] = None) -> VariantExecution:
        body = {
            "prompt": prompt,
            "policy_mode": policy_mode or self.cfg.policy_mode,
            "dept_id": department,
        }
        started = time.perf_counter()
        try:
            resp = requests.post(self.cfg.webhook_url, json=body,
                                 timeout=self.cfg.request_timeout_seconds)
            latency_ms = (time.perf_counter() - started) * 1000.0
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            latency_ms = (time.perf_counter() - started) * 1000.0
            return VariantExecution(
                variant="tokenwise",
                latency_ms=round(latency_ms, 2),
                error=_safe_error(exc),
            )

        payload = data[0] if isinstance(data, list) and data else data
        if not isinstance(payload, dict):
            return VariantExecution(variant="tokenwise", latency_ms=round(latency_ms, 2),
                                    error="invalid_webhook_response")

        answer = (payload.get("answer") or "").strip()
        receipt = payload.get("receipt") or {}
        receipt = receipt if isinstance(receipt, dict) else {}
        parsed = safe_parse_receipt(receipt)

        return VariantExecution(
            variant="tokenwise",
            provider=parsed.get("provider"),
            model=parsed.get("model"),
            answer=answer,
            input_tokens=_as_int(parsed.get("actual_input_tokens")),
            output_tokens=_as_int(parsed.get("actual_output_tokens")),
            total_tokens=_as_int(parsed.get("actual_total_tokens")),
            latency_ms=round(latency_ms, 2),
            actual_cost=_as_float(parsed.get("actual_cost")),
            modeled_baseline_cost=_as_float(parsed.get("estimated_baseline_cost")),
            modeled_optimized_cost=_as_float(
                parsed.get("estimated_optimized_cost") if parsed.get("estimated_optimized_cost") is not None
                else parsed.get("estimated_cost")
            ),
            receipt=parsed,
            error=None if answer else "empty_answer",
        )


def safe_parse_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Return a dict with all known receipt fields; missing ones become None."""
    out: dict[str, Any] = {}
    for key in RECEIPT_FIELDS:
        out[key] = receipt.get(key)
    return out


def _as_int(v: Any) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _as_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _safe_error(exc: Exception) -> str:
    """Concise, secret-free error string (never full stack, never headers)."""
    name = type(exc).__name__
    msg = str(exc)
    if len(msg) > 200:
        msg = msg[:200] + "..."
    return f"{name}: {msg}" if msg else name


# --------------------------------------------------------------------------- #
# Health checks
# --------------------------------------------------------------------------- #
def check_url(url: str, timeout: int = 5) -> tuple[bool, str]:
    try:
        resp = requests.get(url, timeout=timeout)
        return (resp.status_code < 500, f"HTTP {resp.status_code}")
    except Exception as exc:  # noqa: BLE001
        return (False, _safe_error(exc))


def check_ollama(cfg: EvalConfig) -> tuple[bool, str]:
    try:
        resp = requests.get(cfg.ollama_base_url.rstrip("/") + "/api/tags", timeout=10)
        resp.raise_for_status()
        tags = resp.json().get("models", [])
        names = {t.get("name") for t in tags}
        if cfg.judge_model in names or cfg.baseline_model in names:
            return (True, f"ollama ok; models present ({len(names)})")
        return (False, f"required model not found; have {sorted(names)}")
    except Exception as exc:  # noqa: BLE001
        return (False, _safe_error(exc))
