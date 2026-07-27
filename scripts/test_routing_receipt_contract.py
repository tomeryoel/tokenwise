"""Cross-layer contract for RoutingDecisionReceipt v1.

The optimizer (Python), the n8n workflow (JavaScript), and the frontend
(TypeScript) each carry the v1 vocabulary. These tests fail if one layer drifts.

Run:
    python -m pytest scripts/test_routing_receipt_contract.py -q
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "optimizer-service"))

from routing_receipt import (  # noqa: E402
    ALTERNATIVE_KINDS,
    ASSUMPTION_CODES,
    COST_EFFICIENCY_CODES,
    REASON_CODES,
    RECOMMENDATION_BASES,
    ROUTING_PATHS,
    ROUTING_RECEIPT_VERSION,
    ROUTING_TIERS,
)

WORKFLOW_PATH = ROOT / "n8n" / "tokenwise-skeleton.workflow.json"
FRONTEND_TYPES = ROOT / "frontend" / "src" / "types.ts"
FRONTEND_ADAPTER = ROOT / "frontend" / "src" / "routingTransparency.ts"

WORKFLOW = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
NODES = {node["name"]: node for node in WORKFLOW["nodes"]}
PREPARE_CODE = NODES["Prepare Usage Log"]["parameters"]["jsCode"]


def _js_array(name: str, code: str) -> tuple[str, ...]:
    match = re.search(rf"const {name} = \[(.*?)\];", code, re.DOTALL)
    assert match, f"{name} is missing from the workflow code"
    return tuple(re.findall(r"'([^']+)'", match.group(1)))


def _ts_union(name: str, source: str) -> tuple[str, ...]:
    match = re.search(rf"export type {name} =(.*?);", source, re.DOTALL)
    assert match, f"{name} is missing from the frontend types"
    return tuple(re.findall(r'"([^"]+)"', match.group(1)))


# --------------------------------------------------------------------------- #
# Python <-> n8n JavaScript
# --------------------------------------------------------------------------- #
def test_workflow_uses_the_same_receipt_version():
    assert f"'{ROUTING_RECEIPT_VERSION}'" in PREPARE_CODE


def test_workflow_paths_match_python():
    assert _js_array("ROUTING_PATHS", PREPARE_CODE) == ROUTING_PATHS


def test_workflow_tiers_match_python():
    assert _js_array("ROUTING_TIERS", PREPARE_CODE) == ROUTING_TIERS


def test_workflow_bases_match_python_and_exclude_evidence():
    bases = _js_array("ROUTING_BASES", PREPARE_CODE)
    assert bases == RECOMMENDATION_BASES
    assert "evidence_based" not in bases


def test_workflow_reason_codes_match_python():
    assert _js_array("ROUTING_REASON_CODES", PREPARE_CODE) == REASON_CODES


def test_workflow_assumption_codes_match_python():
    assert _js_array("ROUTING_ASSUMPTION_CODES", PREPARE_CODE) == ASSUMPTION_CODES


def test_workflow_cost_codes_match_python():
    assert _js_array("ROUTING_COST_CODES", PREPARE_CODE) == COST_EFFICIENCY_CODES


def test_workflow_alternative_kinds_match_python():
    assert _js_array("ROUTING_ALTERNATIVE_KINDS", PREPARE_CODE) == ALTERNATIVE_KINDS


# --------------------------------------------------------------------------- #
# Workflow shape: one convergence point, unchanged ids and internal URLs
# --------------------------------------------------------------------------- #
def test_routing_is_assembled_in_exactly_one_node():
    writers = [
        name
        for name, node in NODES.items()
        if "receipt.routing" in str(node.get("parameters", {}).get("jsCode", ""))
    ]
    assert writers == ["Prepare Usage Log"]


def test_terminal_builders_do_not_duplicate_the_v1_mapping():
    builders = [name for name in NODES if name.startswith("Build ")]
    assert builders, "workflow lost its terminal response builders"
    for name in builders:
        code = str(NODES[name].get("parameters", {}).get("jsCode", ""))
        assert "routing_receipt_v1" not in code
        assert "ROUTING_PATHS" not in code


def test_workflow_and_webhook_identifiers_are_preserved():
    assert WORKFLOW["id"] == "tokenwiseskeleton"
    assert WORKFLOW["name"] == "MomiHelm Gateway"
    webhook = NODES["Webhook"]
    assert webhook["parameters"]["path"] == "tokenwise"
    assert webhook["webhookId"] == "tokenwise-skeleton"


def test_internal_service_urls_are_preserved():
    urls = {
        node["parameters"]["url"]
        for node in WORKFLOW["nodes"]
        if isinstance(node.get("parameters"), dict) and node["parameters"].get("url")
    }
    assert urls == {
        "http://guardrails-service:8000/check/input",
        "http://guardrails-service:8000/check/output",
        "http://image-analyser-service:8000/analyse",
        "http://optimizer-service:8000/agent/run",
        "http://optimizer-service:8000/providers/execute",
        "http://optimizer-service:8000/usage/log",
        "http://rag-cache-service:8000/cache/lookup",
        "http://rag-cache-service:8000/cache/store",
    }


def test_usage_log_payload_still_omits_routing_metadata():
    """Routing transparency is runtime-only: nothing new is sent to /usage/log."""
    log_node = NODES["Usage Log"]
    body = json.dumps(log_node.get("parameters", {}))
    assert "routing" not in body


# --------------------------------------------------------------------------- #
# Python <-> frontend TypeScript
# --------------------------------------------------------------------------- #
def test_frontend_paths_match_python():
    source = FRONTEND_TYPES.read_text(encoding="utf-8")
    assert _ts_union("RoutingPath", source) == ROUTING_PATHS
    assert _ts_union("RoutingTier", source) == ROUTING_TIERS
    assert _ts_union("RecommendationBasis", source) == RECOMMENDATION_BASES
    assert _ts_union("RoutingAlternativeKind", source) == ALTERNATIVE_KINDS


def test_frontend_has_copy_for_every_reason_and_assumption_code():
    adapter = FRONTEND_ADAPTER.read_text(encoding="utf-8")
    for code in REASON_CODES:
        assert f"{code}:" in adapter, f"frontend is missing copy for reason {code}"
    for code in ASSUMPTION_CODES:
        assert f"{code}:" in adapter, f"frontend is missing copy for assumption {code}"
    for code in COST_EFFICIENCY_CODES:
        assert f"{code}:" in adapter, f"frontend is missing copy for cost code {code}"


def test_frontend_never_labels_confidence_as_calibrated():
    adapter = FRONTEND_ADAPTER.read_text(encoding="utf-8")
    assert "not calibrated" in adapter
    assert "evidence_based" not in adapter
