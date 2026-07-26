"""Minimal stdio MCP server for live MomiHelm Cursor routing tools."""

from __future__ import annotations

import json
import sys
from typing import Any

from connectors.cursor.router import compare_models, list_models, recommend_route


SERVER_NAME = "momihelm-cursor"
SERVER_VERSION = "0.1.0"

TOOLS = [
    {
        "name": "momihelm_list_models",
        "description": (
            "List Cursor models known to MomiHelm (Auto, Composer 2.5, "
            "GPT-5.6 Sol/Terra, Sonnet 5, Grok 4.5, Fable 5, Opus 5)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "momihelm_recommend_model",
        "description": (
            "Recommend which Cursor model to use for a coding task based on "
            "objective, complexity, workflow, and policy mode. Advisory only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "objective": {
                    "type": "string",
                    "description": "The user coding objective or prompt",
                },
                "workflow": {
                    "type": "string",
                    "enum": ["direct", "plan", "agent", "debug", "review", "unknown"],
                    "default": "agent",
                },
                "policy_mode": {
                    "type": "string",
                    "enum": ["conservative", "balanced", "aggressive"],
                    "default": "balanced",
                },
                "prefer_auto": {
                    "type": "boolean",
                    "default": False,
                },
                "requested_model": {
                    "type": "string",
                    "description": "Optional currently selected Cursor model",
                },
            },
            "required": ["objective"],
            "additionalProperties": False,
        },
    },
    {
        "name": "momihelm_compare_models",
        "description": (
            "Compare an executed Cursor model against a recommended model and "
            "report good_fit / overpowered / underpowered."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "executed_model": {"type": "string"},
                "recommended_model": {"type": "string"},
            },
            "required": ["executed_model", "recommended_model"],
            "additionalProperties": False,
        },
    },
]


def _tool_result(payload: Any) -> dict:
    text = json.dumps(payload, indent=2)
    return {"content": [{"type": "text", "text": text}]}


def _call_tool(name: str, arguments: dict) -> dict:
    if name == "momihelm_list_models":
        models = list_models()
        return _tool_result({"models": models, "count": len(models)})
    if name == "momihelm_recommend_model":
        recommendation = recommend_route(
            objective=str(arguments.get("objective", "")),
            workflow=str(arguments.get("workflow", "agent")),
            policy_mode=str(arguments.get("policy_mode", "balanced")),
            prefer_auto=bool(arguments.get("prefer_auto", False)),
            requested_model=arguments.get("requested_model"),
        )
        payload = recommendation.to_dict()
        payload["advisory"] = recommendation.advisory_text()
        return _tool_result(payload)
    if name == "momihelm_compare_models":
        return _tool_result(
            compare_models(
                arguments.get("executed_model"),
                str(arguments.get("recommended_model", "")),
            )
        )
    return {
        "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
        "isError": True,
    }


def _handle(message: dict) -> dict | None:
    method = message.get("method")
    msg_id = message.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": TOOLS},
        }

    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": _call_tool(name, arguments),
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    if msg_id is None:
        return None

    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = _handle(message)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
