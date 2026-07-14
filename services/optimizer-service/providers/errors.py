"""Typed provider errors for Layer 4 model execution."""

from enum import Enum


class ProviderErrorCode(str, Enum):
    PROVIDER_NOT_CONFIGURED = "PROVIDER_NOT_CONFIGURED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    MODEL_NOT_INSTALLED = "MODEL_NOT_INSTALLED"
    TIMEOUT = "TIMEOUT"
    RATE_LIMIT = "RATE_LIMIT"
    PROVIDER_5XX = "PROVIDER_5XX"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    EMPTY_ANSWER = "EMPTY_ANSWER"
    EXECUTION_NOT_REQUIRED = "EXECUTION_NOT_REQUIRED"
    REQUEST_REJECTED = "REQUEST_REJECTED"
    VISION_NOT_SUPPORTED = "VISION_NOT_SUPPORTED"
    PRIVACY_BLOCKED = "PRIVACY_BLOCKED"
    ALL_ATTEMPTS_FAILED = "ALL_ATTEMPTS_FAILED"


class ProviderError(Exception):
    def __init__(self, code: ProviderErrorCode, message: str, provider: str = ""):
        self.code = code
        self.message = message
        self.provider = provider
        super().__init__(message)

    def to_dict(self) -> dict:
        return {"error_code": self.code.value, "message": self.message, "provider": self.provider}
