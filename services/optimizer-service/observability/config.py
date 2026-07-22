"""Environment-backed Langfuse configuration without exposing credentials."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ObservabilityConfig:
    requested_enabled: bool
    public_key: str
    secret_key: str
    base_url: str
    environment: str
    release: str
    flush_on_export: bool
    public_url: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.public_key and self.secret_key and self.base_url)

    @property
    def active(self) -> bool:
        return self.requested_enabled and self.configured

    def browser_trace_url(self, trace_url: str | None) -> str | None:
        """Replace the Docker-only ingestion host with the browser-facing host."""
        if not trace_url:
            return trace_url
        internal = self.base_url.rstrip("/")
        public = (self.public_url or internal).rstrip("/")
        if trace_url == internal or trace_url.startswith(f"{internal}/"):
            return f"{public}{trace_url[len(internal):]}"
        return trace_url

    @classmethod
    def from_env(cls) -> "ObservabilityConfig":
        base_url = os.environ.get("LANGFUSE_BASE_URL", "http://langfuse-web:3000").rstrip("/")
        return cls(
            requested_enabled=_env_bool("LANGFUSE_TRACING_ENABLED"),
            public_key=os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip(),
            secret_key=os.environ.get("LANGFUSE_SECRET_KEY", "").strip(),
            base_url=base_url,
            environment=os.environ.get("LANGFUSE_TRACING_ENVIRONMENT", "development").strip(),
            release=os.environ.get("LANGFUSE_RELEASE", "tokenwise-day-9").strip(),
            flush_on_export=_env_bool("LANGFUSE_FLUSH_ON_EXPORT", default=True),
            public_url=os.environ.get("LANGFUSE_PUBLIC_URL", base_url).strip().rstrip("/"),
        )
