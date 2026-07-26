"""CLI for syncing Cursor local state into MomiHelm."""

from __future__ import annotations

import argparse
import json
import os
import sys

from connectors.cursor.client import MomiHelmConnectorClient
from connectors.cursor.mapper import build_ingest_batch
from connectors.cursor.parser import discover_composers
from connectors.cursor.paths import discover_state_databases
from connectors.cursor.reader import load_cursor_snapshot
from connectors.cursor.router import recommend_route


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def run_sync(args: argparse.Namespace) -> int:
    databases = discover_state_databases()
    if not databases:
        print(
            "No Cursor state.vscdb files found. Set CURSOR_USER_DATA_DIR if Cursor "
            "is installed in a non-default location.",
            file=sys.stderr,
        )
        return 1

    snapshot = load_cursor_snapshot(databases)
    composers = discover_composers(snapshot)
    batch = build_ingest_batch(composers, limit=args.limit)

    if args.dry_run:
        print(f"Discovered databases: {len(databases)}")
        for path in databases:
            print(f"  - {path}")
        print(f"Discovered composers: {batch['discovered_count']}")
        print(f"Selected composers: {batch['selected_count']}")
        for composer in batch["composers"]:
            print(
                f"  - {composer['external_composer_id']}: "
                f"{composer['objective'][:80]!r} "
                f"({len(composer['bubbles'])} assistant turns)"
            )
        return 0

    gateway_url = args.gateway_url or _env("MOMIHELM_GATEWAY_URL", "http://127.0.0.1:5173")
    connector_token = args.connector_token or _env("MOMIHELM_CONNECTOR_TOKEN")
    if not connector_token:
        print(
            "Set MOMIHELM_CONNECTOR_TOKEN in .env or pass --connector-token.",
            file=sys.stderr,
        )
        return 1

    client = MomiHelmConnectorClient(
        gateway_url=gateway_url,
        connector_token=connector_token,
        timeout_seconds=args.timeout_seconds,
    )
    result = client.ingest_cursor_batch(batch)
    print(f"Discovered composers: {result.discovered_count}")
    print(f"Selected composers: {result.selected_count}")
    print(f"Sessions created: {result.sessions_created}")
    print(f"Sessions updated: {result.sessions_updated}")
    print(f"Attempts created: {result.attempts_created}")
    print(f"Attempts skipped: {result.attempts_skipped}")
    for link in result.composer_links:
        print(
            f"  cursor {link['external_composer_id']} -> session {link['session_id']}"
        )
    return 0


def run_recommend(args: argparse.Namespace) -> int:
    recommendation = recommend_route(
        objective=args.objective,
        workflow=args.workflow,
        policy_mode=args.policy_mode,
        prefer_auto=args.prefer_auto,
        requested_model=args.requested_model or None,
    )
    if args.json:
        print(json.dumps(recommendation.to_dict(), indent=2))
    else:
        print(recommendation.advisory_text())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="connectors.cursor",
        description="Sync Cursor local composer history into MomiHelm.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    recommend = subparsers.add_parser(
        "recommend",
        help="Recommend a Cursor model for an objective (offline, no Docker required)",
    )
    recommend.add_argument("objective", help="Coding objective / prompt text")
    recommend.add_argument(
        "--workflow",
        default="agent",
        choices=["direct", "plan", "agent", "debug", "review", "unknown"],
    )
    recommend.add_argument(
        "--policy-mode",
        default="balanced",
        choices=["conservative", "balanced", "aggressive"],
    )
    recommend.add_argument("--requested-model", default="")
    recommend.add_argument("--prefer-auto", action="store_true")
    recommend.add_argument("--json", action="store_true")
    recommend.set_defaults(func=run_recommend)

    sync = subparsers.add_parser("sync", help="Read Cursor state.vscdb and ingest into MomiHelm")
    sync.add_argument(
        "--gateway-url",
        default="",
        help="MomiHelm gateway URL (default: MOMIHELM_GATEWAY_URL or http://127.0.0.1:5173)",
    )
    sync.add_argument(
        "--connector-token",
        default="",
        help="Connector token (default: MOMIHELM_CONNECTOR_TOKEN)",
    )
    sync.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of recent composers to ingest",
    )
    sync.add_argument(
        "--timeout-seconds",
        type=int,
        default=60,
        help="HTTP timeout for MomiHelm ingest",
    )
    sync.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect local Cursor data without posting to MomiHelm",
    )
    sync.set_defaults(func=run_sync)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
