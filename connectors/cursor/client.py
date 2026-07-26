"""HTTP client for posting Cursor ingest payloads to MomiHelm."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class SyncResult:
    discovered_count: int
    selected_count: int
    sessions_created: int
    sessions_updated: int
    attempts_created: int
    attempts_skipped: int
    composer_links: list[dict[str, str]]


class MomiHelmConnectorClient:
    def __init__(
        self,
        *,
        gateway_url: str,
        connector_token: str,
        timeout_seconds: int = 60,
    ) -> None:
        self.gateway_url = gateway_url.rstrip("/")
        self.connector_token = connector_token
        self.timeout_seconds = timeout_seconds

    def ingest_cursor_batch(self, payload: dict) -> SyncResult:
        url = f"{self.gateway_url}/api/connectors/cursor/ingest"
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-MomiHelm-Connector-Token": self.connector_token,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"MomiHelm ingest failed ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach MomiHelm at {url}: {exc}") from exc

        return SyncResult(
            discovered_count=int(data.get("discovered_count", payload.get("discovered_count", 0))),
            selected_count=int(data.get("selected_count", payload.get("selected_count", 0))),
            sessions_created=int(data.get("sessions_created", 0)),
            sessions_updated=int(data.get("sessions_updated", 0)),
            attempts_created=int(data.get("attempts_created", 0)),
            attempts_skipped=int(data.get("attempts_skipped", 0)),
            composer_links=list(data.get("composer_links", [])),
        )
