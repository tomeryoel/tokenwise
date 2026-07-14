"""Configurable static pricing for provider cost calculation."""

import json
import os
from pathlib import Path

DEFAULT_PRICING_PATH = "/app/config/model_pricing.json"


def _load_pricing() -> dict:
    path = os.environ.get("MODEL_PRICING_CONFIG_PATH", DEFAULT_PRICING_PATH)
    p = Path(path)
    if not p.exists():
        return {"models": {}}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    provider: str = "",
) -> tuple[float | None, str]:
    """Return (actual_cost, cost_calculation_status).

    Ollama/local models always return 0 with status 'local_zero_api_cost'.
    Unknown paid models return (None, 'pricing_not_configured').
    """
    if provider == "ollama":
        return 0.0, "local_zero_api_cost"

    pricing = _load_pricing()
    models = pricing.get("models", {})
    entry = models.get(model)
    if not entry:
        return None, "pricing_not_configured"

    input_per_m = float(entry.get("input_per_million", 0))
    output_per_m = float(entry.get("output_per_million", 0))
    input_cost = (input_tokens / 1_000_000) * input_per_m
    output_cost = (output_tokens / 1_000_000) * output_per_m
    total = round(input_cost + output_cost, 8)
    return total, "calculated"
