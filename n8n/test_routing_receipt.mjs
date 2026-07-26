/**
 * Executes the real "Prepare Usage Log" code from the exported n8n workflow and
 * checks the RoutingDecisionReceipt v1 object it builds for every terminal
 * branch. The code is read out of the workflow JSON, so the test fails if the
 * shipped workflow drifts from the expected receipt contract.
 *
 * Run:
 *   docker run --rm -v "$PWD/n8n:/n8n:ro" -w /n8n node:20-alpine \
 *     node --test test_routing_receipt.mjs
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const workflowPath = join(
  dirname(fileURLToPath(import.meta.url)),
  "tokenwise-skeleton.workflow.json",
);
const workflow = JSON.parse(readFileSync(workflowPath, "utf8"));
const prepareNode = workflow.nodes.find((node) => node.name === "Prepare Usage Log");
assert.ok(prepareNode, "workflow is missing the Prepare Usage Log node");
const prepareCode = prepareNode.parameters.jsCode;

/** Run the node code with the n8n helpers it relies on. */
function runPrepare({ body, normalize = {}, guardrails, optimizer, provider }) {
  const items = {
    Normalize: [{ json: normalize }],
  };
  if (guardrails !== undefined) items.Guardrails = [{ json: guardrails }];
  if (optimizer !== undefined) items.Optimizer = [{ json: optimizer }];
  if (provider !== undefined) items["Provider Execute"] = [{ json: provider }];

  const runner = new Function(
    "$json",
    "$items",
    "$",
    `"use strict";\n${prepareCode}`,
  );
  const output = runner(
    body,
    (name) => {
      if (!(name in items)) throw new Error(`no node named ${name}`);
      return items[name];
    },
    (name) => ({ item: { json: items[name] ? items[name][0].json : {} } }),
  );
  return output[0].json;
}

const LOCAL_RECOMMENDATION = {
  version: "routing_receipt_v1",
  recommended: {
    path: "local_ollama",
    tier: "cheap",
    provider: "ollama",
    model: "llama3.1:latest",
  },
  selected: { path: null, tier: null, provider: null, model: null },
  executed: { path: null, tier: null, provider: null, model: null },
  basis: "heuristic",
  reason_codes: ["no_repo_edit_required", "simple_task", "local_model_available"],
  assumptions: ["no_historical_performance_data", "static_model_catalog"],
  confidence: { value: 0.55, calibration: "not_calibrated" },
  alternatives: [
    {
      kind: "unavailable",
      target: { path: "external_model", tier: "balanced", provider: "openai", model: null },
      reason_codes: ["external_model_unavailable"],
    },
  ],
  cost_efficiency: {
    code: "local_capability_sufficient",
    estimated_baseline_cost_usd: 0.0021,
    estimated_selected_cost_usd: 0,
    estimated_savings_usd: 0.0021,
  },
};

const LOCAL_TARGET = {
  path: "local_ollama",
  tier: "cheap",
  provider: "ollama",
  model: "llama3.1:latest",
};

function localRun(overrides = {}) {
  return runPrepare({
    body: {
      answer: "Semantic caching reuses previous answers.",
      receipt: {
        guardrail_status: "passed",
        cache_status: "miss",
        selected_tier: "cheap",
        requested_tier: "cheap",
        executed_tier: "cheap",
        provider: "ollama",
        model: "llama3.1:latest",
        actual_cost: 0,
        ...overrides.receipt,
      },
    },
    normalize: { request_id: "req-1", prompt: "explain semantic caching" },
    optimizer: { routing_recommendation: LOCAL_RECOMMENDATION, ...overrides.optimizer },
    provider: {
      selected_target: LOCAL_TARGET,
      executed_target: LOCAL_TARGET,
      ...overrides.provider,
    },
  });
}

test("a local run reports the same route at all three stages", () => {
  const routing = localRun().receipt.routing;
  assert.equal(routing.version, "routing_receipt_v1");
  assert.deepEqual(routing.recommended, LOCAL_TARGET);
  assert.deepEqual(routing.selected, LOCAL_TARGET);
  assert.deepEqual(routing.executed, LOCAL_TARGET);
  assert.equal(routing.basis, "heuristic");
  assert.ok(!routing.reason_codes.includes("selected_differs_from_recommended"));
  assert.ok(!routing.reason_codes.includes("executed_differs_from_selected"));
  assert.equal(routing.cost_efficiency.code, "local_capability_sufficient");
  assert.equal(routing.cost_efficiency.actual_executed_cost_usd, 0);
  assert.equal(routing.confidence.calibration, "not_calibrated");
});

test("a provider fallback is visible as a selected/executed mismatch", () => {
  const routing = localRun({
    receipt: { used_fallback: true, fallback_reason: "provider_error" },
    provider: {
      selected_target: {
        path: "external_model",
        tier: "cheap",
        provider: "openai",
        model: "gpt-4o-mini",
      },
      executed_target: {
        path: "local_ollama",
        tier: "balanced",
        provider: "ollama",
        model: "llama3.1:latest",
      },
    },
  }).receipt.routing;
  assert.equal(routing.selected.path, "external_model");
  assert.equal(routing.executed.path, "local_ollama");
  assert.ok(routing.reason_codes.includes("provider_fallback"));
  assert.ok(routing.reason_codes.includes("executed_differs_from_selected"));
  assert.ok(routing.reason_codes.includes("selected_differs_from_recommended"));
});

test("a configured fallback that did not change the route is not called a fallback", () => {
  // used_fallback is also set when the external provider is simply not
  // configured. Nothing failed mid-run and the route never changed, so the
  // receipt must not imply a provider failure.
  const routing = localRun({
    receipt: { used_fallback: true, fallback_reason: "external_provider_not_configured" },
  }).receipt.routing;
  assert.deepEqual(routing.selected, routing.executed);
  assert.ok(!routing.reason_codes.includes("provider_fallback"));
  assert.ok(!routing.reason_codes.includes("executed_differs_from_selected"));
});

test("a cache hit reports the semantic cache and no model", () => {
  const routing = runPrepare({
    body: {
      answer: "Cached answer.",
      receipt: {
        guardrail_status: "passed",
        cache_status: "hit",
        cache_confidence: 0.94,
        provider: "not called (semantic cache hit)",
        selected_tier: "cache",
      },
    },
    normalize: { request_id: "req-2" },
    optimizer: {},
  }).receipt.routing;
  assert.deepEqual(routing.selected, {
    path: "semantic_cache",
    tier: "cache",
    provider: null,
    model: null,
  });
  assert.deepEqual(routing.executed, routing.selected);
  assert.equal(routing.executed.model, null);
  assert.ok(routing.reason_codes.includes("semantic_cache_hit"));
  assert.equal(routing.cost_efficiency.code, "cache_reuse_avoided_model_call");
});

test("a guardrail block reports no execution and never a provider", () => {
  const routing = runPrepare({
    body: {
      answer: null,
      receipt: {
        guardrail_status: "blocked",
        reason: "prompt_injection",
        cache_status: "skipped",
        provider: "not called (blocked by guardrails)",
        selected_tier: "reject",
      },
    },
    normalize: { request_id: "req-3" },
    guardrails: { reason: "prompt_injection" },
  }).receipt.routing;
  assert.deepEqual(routing.executed, {
    path: "no_execution",
    tier: "none",
    provider: null,
    model: null,
  });
  assert.deepEqual(routing.recommended, routing.executed);
  assert.ok(routing.reason_codes.includes("guardrail_blocked"));
  assert.equal(routing.cost_efficiency.code, "no_execution_no_model_cost");
});

test("the vision path reports the local image service", () => {
  const routing = runPrepare({
    body: {
      answer: "The image shows a diagram.",
      receipt: {
        guardrail_status: "passed",
        cache_status: "skipped",
        selected_tier: "vision",
        provider: "image-analyser-service",
        model: "moondream:1.8b",
        has_image: true,
      },
    },
    normalize: { request_id: "req-4" },
    optimizer: {},
  }).receipt.routing;
  assert.equal(routing.executed.path, "local_service");
  assert.equal(routing.executed.tier, "vision");
  assert.equal(routing.executed.provider, "image-analyser-service");
  assert.equal(routing.cost_efficiency.code, "local_capability_sufficient");
});

test("a provider error keeps the executed stage empty instead of claiming success", () => {
  const routing = localRun({
    receipt: {
      error_code: "ALL_PROVIDERS_FAILED",
      provider: "ollama",
      model: "llama3.1:latest",
      executed_tier: null,
      actual_cost: null,
    },
    provider: {
      selected_target: LOCAL_TARGET,
      executed_target: { path: null, tier: null, provider: null, model: null },
    },
  }).receipt.routing;
  assert.equal(routing.selected.path, "local_ollama");
  assert.equal(routing.executed.path, null);
  assert.equal(routing.executed.model, null);
  assert.equal(routing.cost_efficiency.actual_executed_cost_usd, null);
  assert.ok(!routing.reason_codes.includes("executed_differs_from_selected"));
});

test("a paid selection over a local recommendation is flagged", () => {
  const routing = localRun({
    provider: {
      selected_target: {
        path: "external_model",
        tier: "premium",
        provider: "openai",
        model: "gpt-4o",
      },
      executed_target: {
        path: "external_model",
        tier: "premium",
        provider: "openai",
        model: "gpt-4o",
      },
    },
  }).receipt.routing;
  assert.ok(routing.reason_codes.includes("selected_differs_from_recommended"));
  assert.ok(routing.reason_codes.includes("user_selected_paid_path"));
});

test("a missing optimizer recommendation degrades without inventing a route", () => {
  const routing = runPrepare({
    body: {
      answer: "Answer.",
      receipt: {
        guardrail_status: "passed",
        cache_status: "miss",
        selected_tier: "cheap",
        provider: "ollama",
        model: "llama3.1:latest",
      },
    },
    normalize: { request_id: "req-5" },
    optimizer: {},
  }).receipt.routing;
  assert.equal(routing.recommended.path, null);
  assert.equal(routing.recommended.model, null);
  assert.equal(routing.selected.path, "local_ollama");
  assert.equal(routing.basis, "configured");
  assert.deepEqual(routing.alternatives, [
    { kind: "unavailable", target: null, reason_codes: ["no_applicable_alternative"] },
  ]);
  assert.deepEqual(routing.reason_codes, []);
});

test("the receipt never carries prompt, answer, or diff content", () => {
  const output = localRun();
  const routing = output.receipt.routing;
  const serialized = JSON.stringify(routing);
  assert.ok(!serialized.includes("semantic caching"));
  assert.ok(!serialized.includes("Semantic caching reuses"));
  assert.deepEqual(routing.fingerprints, { prompt: null, result: null, diff: null });
  // The usage log still receives the prompt for hashing during persistence; the
  // routing receipt itself stays metadata-only.
  assert.equal(output.usage_log.prompt, "explain semantic caching");
});

test("unknown enum values from upstream are dropped, not passed through", () => {
  const routing = localRun({
    optimizer: {
      routing_recommendation: {
        ...LOCAL_RECOMMENDATION,
        basis: "evidence_based",
        reason_codes: ["simple_task", "made_up_code"],
        assumptions: ["static_model_catalog", "made_up_assumption"],
        cost_efficiency: { code: "made_up_cost_code" },
      },
    },
  }).receipt.routing;
  assert.equal(routing.basis, "configured");
  assert.ok(!routing.reason_codes.includes("made_up_code"));
  assert.ok(!routing.assumptions.includes("made_up_assumption"));
  assert.equal(routing.cost_efficiency.code, "cost_comparison_unavailable");
});

test("existing usage-log fields keep working alongside the receipt", () => {
  const output = localRun({ receipt: { latency_ms: 812, actual_total_tokens: 96 } });
  assert.equal(output.usage_log.request_id, "req-1");
  assert.equal(output.usage_log.status, "completed");
  assert.equal(output.usage_log.latency_ms, 812);
  assert.equal(output.usage_log.actual_total_tokens, 96);
  assert.equal(output.usage_log.provider, "ollama");
  assert.equal(output.answer, "Semantic caching reuses previous answers.");
});
