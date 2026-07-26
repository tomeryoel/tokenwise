#!/usr/bin/env python3
"""Cursor hook helpers for live MomiHelm routing advice."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _ensure_path() -> None:
    root = str(_repo_root())
    if root not in sys.path:
        sys.path.insert(0, root)


def _read_stdin() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _write_route_log(payload: dict) -> None:
    log_dir = _repo_root() / ".momihelm"
    log_dir.mkdir(parents=True, exist_ok=True)
    latest = log_dir / "last-route.json"
    latest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    history = log_dir / "route-log.jsonl"
    with history.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def session_start() -> int:
    _ensure_path()
    event = _read_stdin()
    mode = str(event.get("composer_mode") or "agent")
    context = (
        "MomiHelm is enabled for this Cursor session.\n"
        "Before expensive or ambiguous coding work, call the MCP tool "
        "`momihelm_recommend_model` with the user objective.\n"
        "Prefer the recommended Cursor model when selecting models "
        "(Composer 2.5, GPT-5.6 Sol/Terra, Sonnet 5, Grok 4.5, Fable 5, Opus 5, Auto).\n"
        f"Current composer mode hint: {mode}.\n"
        "Recommendations are advisory; they do not auto-switch Cursor models."
    )
    print(
        json.dumps(
            {
                "additional_context": context,
                "env": {
                    "MOMIHELM_LIVE_ROUTING": "1",
                    "MOMIHELM_COMPOSER_MODE": mode,
                },
            }
        )
    )
    return 0


def before_prompt() -> int:
    _ensure_path()
    from connectors.cursor.router import recommend_route

    event = _read_stdin()
    prompt = str(event.get("prompt") or "").strip()
    if not prompt:
        print(json.dumps({"continue": True}))
        return 0

    workflow = os.environ.get("MOMIHELM_COMPOSER_MODE", "agent")
    policy_mode = os.environ.get("MOMIHELM_POLICY_MODE", "balanced")
    recommendation = recommend_route(
        objective=prompt,
        workflow=workflow,
        policy_mode=policy_mode,
    )
    payload = recommendation.to_dict()
    payload.update(
        {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "prompt_chars": len(prompt),
            "source": "beforeSubmitPrompt",
        }
    )
    try:
        _write_route_log(payload)
    except OSError:
        pass

    # Fail-open: never block submission. Context injection on this event is
    # limited, so we also persist the recommendation for MCP/Dashboard use.
    print(json.dumps({"continue": True}))
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: momihelm_route_hook.py <session_start|before_prompt>", file=sys.stderr)
        return 1
    command = argv[1]
    if command == "session_start":
        return session_start()
    if command == "before_prompt":
        return before_prompt()
    print(f"unknown command: {command}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
