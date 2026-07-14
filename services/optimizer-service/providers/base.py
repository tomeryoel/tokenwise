"""Abstract provider interface for Layer 4 model execution."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ProviderResult:
    success: bool
    answer: str = ""
    provider: str = ""
    model: str = ""
    actual_input_tokens: int = 0
    actual_output_tokens: int = 0
    actual_total_tokens: int = 0
    actual_cost: float | None = 0.0
    latency_ms: int = 0
    provider_total_duration_ms: int | None = None
    provider_load_duration_ms: int | None = None
    provider_request_id: str | None = None
    cost_calculation_status: str = "not_applicable"
    error_code: str | None = None
    error_message: str | None = None


class BaseProvider(ABC):
    name: str = "base"

    @abstractmethod
    def is_configured(self) -> bool:
        ...

    @abstractmethod
    async def execute(self, prompt: str, model: str, system_prompt: str = "") -> ProviderResult:
        ...

    @abstractmethod
    async def check_health(self) -> dict:
        ...
