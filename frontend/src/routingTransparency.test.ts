/**
 * Routing transparency adapter tests.
 *
 * These run on the Node built-in test runner, bundled with the esbuild that
 * already ships with Vite, so no extra dependency is required:
 *
 *   docker run --rm -v "$PWD/frontend:/src:ro" -w /build node:20-alpine sh -lc \
 *     "cp -r /src/. /build && npm ci --silent && \
 *      ./node_modules/.bin/esbuild src/routingTransparency.test.ts --bundle \
 *        --platform=node --format=cjs --outfile=routing.test.cjs && \
 *      node --test routing.test.cjs"
 */
import assert from "node:assert/strict";
import test from "node:test";

import {
  buildRoutingView,
  mergeCursorRouting,
  NOT_RECORDED,
} from "./routingTransparency";
import type { RoutingDecisionReceipt } from "./types";

const localTarget = {
  path: "local_ollama" as const,
  tier: "cheap" as const,
  provider: "ollama",
  model: "llama3.1:latest",
};

function receipt(overrides: Partial<RoutingDecisionReceipt> = {}): RoutingDecisionReceipt {
  return {
    version: "routing_receipt_v1",
    recommended: localTarget,
    selected: localTarget,
    executed: localTarget,
    basis: "heuristic",
    reason_codes: ["simple_task", "no_repo_edit_required"],
    assumptions: ["no_historical_performance_data"],
    confidence: { value: 0.55, calibration: "not_calibrated" },
    alternatives: [],
    cost_efficiency: { code: "local_capability_sufficient" },
    fingerprints: { prompt: null, result: null, diff: null },
    ...overrides,
  };
}

function stage(view: ReturnType<typeof buildRoutingView>, name: string) {
  const found = view?.stages.find((item) => item.name === name);
  assert.ok(found, `missing stage ${name}`);
  return found;
}

test("a simple Quick Question run shows local Ollama at every stage without warnings", () => {
  const view = buildRoutingView(receipt());
  assert.ok(view);
  assert.equal(stage(view, "Recommended").path, "Local Ollama");
  assert.equal(stage(view, "Selected").path, "Local Ollama");
  assert.equal(stage(view, "Executed").model, "llama3.1:latest");
  assert.deepEqual(view.warnings, []);
  assert.equal(view.basis, "Heuristic");
  assert.equal(view.confidence, "55% (not calibrated)");
});

test("a Cursor repo-edit run shows the Cursor SDK path", () => {
  const cursorTarget = {
    path: "cursor_sdk" as const,
    tier: "cheap" as const,
    provider: "cursor-sdk",
    model: "composer-2.5-fast",
  };
  const view = buildRoutingView(
    receipt({
      recommended: cursorTarget,
      selected: cursorTarget,
      executed: cursorTarget,
      reason_codes: ["repo_edit_required", "diff_capture_required", "validation_required"],
      cost_efficiency: { code: "paid_execution_justified" },
    }),
  );
  assert.ok(view);
  assert.equal(stage(view, "Executed").path, "Cursor SDK");
  assert.deepEqual(view.warnings, []);
  assert.ok(view.reasons.includes("Repository file edits are required."));
  assert.match(view.costHeadline, /paid route is justified/);
});

test("choosing a paid model over a local recommendation is called out", () => {
  const paid = {
    path: "cursor_sdk" as const,
    tier: "premium" as const,
    provider: "cursor-sdk",
    model: "claude-opus-5-thinking-high",
  };
  const view = buildRoutingView(
    receipt({
      recommended: { path: "local_ollama", tier: "local", provider: "ollama" },
      selected: paid,
      executed: paid,
      reason_codes: ["selected_differs_from_recommended", "user_selected_paid_path"],
    }),
  );
  assert.ok(view);
  const texts = view.warnings.map((warning) => warning.text);
  assert.ok(texts.some((item) => item.includes("differs from the recommended route")));
  assert.ok(texts.some((item) => item.includes("more expensive than the recommendation")));
  assert.ok(
    view.reasons.includes(
      "A paid path was selected although a local path was recommended.",
    ),
  );
});

test("a model mismatch between selected and executed is visible", () => {
  const view = buildRoutingView(
    receipt({
      selected: { path: "cursor_sdk", provider: "cursor-sdk", model: "composer-2.5-fast" },
      executed: { path: "cursor_sdk", provider: "cursor-sdk", model: "gpt-5.6-terra-medium" },
    }),
  );
  assert.ok(view);
  assert.ok(
    view.warnings.some((warning) =>
      warning.text.includes("differs from the selected route"),
    ),
  );
});

test("a stage detail line omits parts that were not recorded", () => {
  const view = buildRoutingView(
    receipt({
      recommended: { path: "semantic_cache", tier: "cache" },
      selected: { path: "cursor_sdk", provider: "cursor-sdk" },
    }),
  );
  assert.ok(view);
  assert.equal(stage(view, "Recommended").detail, "Cache");
  assert.equal(stage(view, "Selected").detail, "Cursor SDK");
  assert.equal(stage(view, "Executed").detail, "Local Ollama · Cheap tier");
});

test("a cache hit reports no executed model", () => {
  const cached = { path: "semantic_cache" as const, tier: "cache" as const };
  const view = buildRoutingView(
    receipt({
      recommended: cached,
      selected: cached,
      executed: cached,
      reason_codes: ["semantic_cache_hit"],
      cost_efficiency: { code: "cache_reuse_avoided_model_call" },
    }),
  );
  assert.ok(view);
  assert.equal(stage(view, "Executed").path, "Semantic cache");
  assert.equal(stage(view, "Executed").model, NOT_RECORDED);
  assert.equal(stage(view, "Executed").provider, NOT_RECORDED);
  assert.ok(
    view.warnings.some((warning) => warning.text.includes("No model was executed")),
  );
});

test("a guardrail block reports no execution and no provider", () => {
  const blocked = { path: "no_execution" as const, tier: "none" as const };
  const view = buildRoutingView(
    receipt({
      recommended: blocked,
      selected: blocked,
      executed: blocked,
      reason_codes: ["guardrail_blocked"],
      cost_efficiency: { code: "no_execution_no_model_cost" },
    }),
  );
  assert.ok(view);
  assert.equal(stage(view, "Executed").path, "No execution");
  assert.equal(stage(view, "Executed").model, NOT_RECORDED);
  assert.match(view.costHeadline, /no model cost/);
});

test("a provider fallback from an external model to local is shown as a mismatch", () => {
  const view = buildRoutingView(
    receipt({
      recommended: { path: "external_model", tier: "balanced", provider: "openai", model: "gpt-x" },
      selected: { path: "external_model", tier: "balanced", provider: "openai", model: "gpt-x" },
      executed: localTarget,
      reason_codes: ["provider_fallback", "executed_differs_from_selected"],
    }),
  );
  assert.ok(view);
  assert.ok(
    view.warnings.some((warning) =>
      warning.text.includes("differs from the selected route"),
    ),
  );
  assert.ok(view.reasons.includes("The provider fell back to another target."));
});

test("an old response without a routing receipt renders nothing", () => {
  assert.equal(buildRoutingView(undefined), null);
  assert.equal(buildRoutingView(null), null);
});

test("partial receipts report unrecorded stages instead of guessing", () => {
  const view = buildRoutingView({
    version: "routing_receipt_v1",
    recommended: { path: "cursor_sdk", tier: "cheap", provider: "cursor-sdk", model: "composer-2.5-fast" },
  });
  assert.ok(view);
  assert.equal(stage(view, "Recommended").recorded, true);
  assert.equal(stage(view, "Selected").recorded, false);
  assert.equal(stage(view, "Selected").path, NOT_RECORDED);
  assert.equal(stage(view, "Executed").model, NOT_RECORDED);
  assert.deepEqual(view.warnings, []);
  assert.equal(view.basis, NOT_RECORDED);
  assert.equal(view.confidence, `${NOT_RECORDED} (not calibrated)`);
});

test("unknown codes are passed through instead of dropped", () => {
  const view = buildRoutingView(
    receipt({ reason_codes: ["brand_new_code"], assumptions: ["brand_new_assumption"] }),
  );
  assert.ok(view);
  assert.deepEqual(view.reasons, ["brand_new_code"]);
  assert.deepEqual(view.assumptions, ["brand_new_assumption"]);
});

test("the frozen pre-run recommendation survives the post-run merge", () => {
  const frozen = receipt({
    recommended: { path: "local_ollama", tier: "local", provider: "ollama" },
  });
  const server = receipt({
    recommended: { path: "cursor_sdk", tier: "cheap", provider: "cursor-sdk", model: "composer-2.5-fast" },
    selected: { path: "cursor_sdk", tier: "premium", provider: "cursor-sdk", model: "claude-opus-5-thinking-high" },
    executed: { path: "cursor_sdk", tier: "premium", provider: "cursor-sdk", model: "claude-opus-5-thinking-high" },
  });
  const merged = mergeCursorRouting(frozen, server);
  assert.equal(merged?.recommended?.path, "local_ollama");
  assert.equal(merged?.selected?.model, "claude-opus-5-thinking-high");
  assert.equal(mergeCursorRouting(frozen, null)?.recommended?.path, "local_ollama");
  assert.equal(mergeCursorRouting(null, server)?.recommended?.path, "cursor_sdk");
});

test("the view never exposes free-text prompt or diff content", () => {
  const view = buildRoutingView(
    receipt({
      fingerprints: { prompt: "a1b2c3", result: "d4e5f6", diff: null },
    }),
  );
  assert.ok(view);
  assert.deepEqual(
    view.fingerprints.map((row) => row.value),
    ["a1b2c3", "d4e5f6", NOT_RECORDED],
  );
});
