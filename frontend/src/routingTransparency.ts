import type {
  RoutingAlternative,
  RoutingDecisionReceipt,
  RoutingTarget,
} from "./types";

/**
 * Presentation adapter for RoutingDecisionReceipt v1.
 *
 * It only reads what the backend reported. It never computes a route, never
 * invents a provider or model, and never upgrades an unknown stage into a
 * guess: unrecorded values render as "Not recorded".
 */

export const NOT_RECORDED = "Not recorded";

export type RoutingStageName = "Recommended" | "Selected" | "Executed";

export interface RoutingStageView {
  name: RoutingStageName;
  recorded: boolean;
  path: string;
  tier: string;
  provider: string;
  model: string;
  /** Provider and tier, with unrecorded parts left out. */
  detail: string;
}

export interface RoutingWarningView {
  tone: "warning" | "info";
  text: string;
}

export interface RoutingAlternativeView {
  kind: string;
  label: string;
  target: string;
  reasons: string[];
}

export interface RoutingCostRow {
  label: string;
  value: string;
}

export interface RoutingTransparencyView {
  version: string;
  stages: RoutingStageView[];
  basis: string;
  basisDetail: string;
  confidence: string;
  reasons: string[];
  assumptions: string[];
  alternatives: RoutingAlternativeView[];
  costHeadline: string;
  costRows: RoutingCostRow[];
  warnings: RoutingWarningView[];
  fingerprints: RoutingCostRow[];
}

const PATH_COPY: Record<string, string> = {
  local_ollama: "Local Ollama",
  cursor_sdk: "Cursor SDK",
  external_model: "External model provider",
  local_service: "Local MomiHelm service",
  semantic_cache: "Semantic cache",
  no_execution: "No execution",
};

const TIER_COPY: Record<string, string> = {
  local: "Local tier",
  cheap: "Cheap tier",
  balanced: "Balanced tier",
  premium: "Premium tier",
  vision: "Vision tier",
  cache: "Cache",
  none: "No tier",
};

const BASIS_COPY: Record<string, string> = {
  heuristic: "Heuristic",
  configured: "Configured",
};

const BASIS_DETAIL: Record<string, string> = {
  heuristic:
    "Keyword and complexity heuristics chose this route. No historical performance data was used.",
  configured:
    "Policy or configuration decided this route directly, not a learned model.",
};

const REASON_COPY: Record<string, string> = {
  simple_task: "The request looks simple.",
  explanation_only: "The request asks for an explanation.",
  summary_only: "The request asks for a summary.",
  lightweight_planning: "The request is lightweight planning.",
  no_repo_edit_required: "No repository edit is required.",
  local_model_available: "A local model is configured for this tier.",
  local_model_unavailable: "No local model is configured for this tier.",
  cost_saving_available:
    "This route costs less than a premium baseline for the same request.",
  repo_edit_required: "Repository file edits are required.",
  diff_capture_required: "A diff of the changes is required.",
  validation_required: "A validation command has to run.",
  multi_file_reasoning: "Reasoning across multiple files is required.",
  higher_risk_change: "The change carries higher risk.",
  local_model_insufficient: "The local model does not cover this request.",
  policy_requires_stronger_model:
    "The organization policy asks for a stronger model here.",
  policy_requires_local_model: "Policy requires local execution.",
  policy_blocks_external_model: "Policy blocks external model providers.",
  external_model_configured: "An external model provider is configured.",
  external_model_unavailable: "No external model provider is configured.",
  user_selected_paid_path:
    "A paid path was selected although a local path was recommended.",
  semantic_cache_hit: "A cached answer matched this request.",
  guardrail_blocked: "Guardrails blocked the request before execution.",
  provider_fallback: "The provider fell back to another target.",
  selected_differs_from_recommended:
    "The selected route differs from the recommendation.",
  executed_differs_from_selected:
    "The executed route differs from the selected route.",
  no_applicable_alternative: "No applicable alternative was available.",
};

const ASSUMPTION_COPY: Record<string, string> = {
  no_historical_performance_data:
    "No historical performance data is available yet.",
  static_model_catalog: "A static model catalog was used.",
  heuristic_task_classification: "Task classification is heuristic.",
  ollama_health_passed: "The local Ollama health check passed.",
  ollama_health_unknown:
    "Local Ollama health was not checked; only its configuration is known.",
  cursor_bridge_health_passed: "The Cursor bridge responded to this run.",
  cursor_bridge_health_unknown: "Cursor bridge health was not checked.",
  external_provider_configured: "An external provider is configured.",
  external_provider_not_configured: "No external provider is configured.",
  task_requires_repository_edits:
    "The objective appears to require repository edits.",
  validation_command_provided: "A validation command was provided.",
  no_repository_edit_detected: "No repository edit signal was detected.",
  policy_allows_local_model: "Policy allows local model execution.",
  policy_allows_external_model: "Policy allows external model execution.",
};

const ALTERNATIVE_COPY: Record<string, string> = {
  cheaper: "Cheaper option",
  stronger: "Stronger option",
  safer: "Safer option",
  unavailable: "Unavailable",
  blocked_by_policy: "Blocked by policy",
};

const COST_COPY: Record<string, string> = {
  local_capability_sufficient:
    "A local model is enough for this request, so paid capacity is not needed.",
  paid_execution_justified:
    "The paid route is justified because the task needs capabilities the local path does not provide.",
  stronger_model_justified:
    "A stronger model is justified by the complexity or risk of this task.",
  cache_reuse_avoided_model_call:
    "Reusing the cached answer avoided a model call entirely.",
  no_execution_no_model_cost:
    "Nothing was executed, so no model cost was incurred.",
  cost_comparison_unavailable:
    "MomiHelm does not have enough cost data to compare routes for this run.",
};

function text(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function describePath(path: unknown): string {
  const key = text(path);
  if (!key) return NOT_RECORDED;
  return PATH_COPY[key] ?? key;
}

function describeTier(tier: unknown): string {
  const key = text(tier);
  if (!key) return NOT_RECORDED;
  return TIER_COPY[key] ?? key;
}

function describeProvider(provider: unknown): string {
  const key = text(provider);
  if (!key) return NOT_RECORDED;
  if (key === "ollama") return "Local Ollama";
  if (key === "openai") return "OpenAI";
  if (key === "cursor-sdk") return "Cursor SDK";
  return key;
}

function stageView(name: RoutingStageName, target?: RoutingTarget | null): RoutingStageView {
  const path = text(target?.path);
  const tier = text(target?.tier);
  const provider = text(target?.provider);
  const model = text(target?.model);
  // Cache and no-execution stages have no provider by design, so the detail
  // line lists only the parts that were actually recorded.
  const detail = [
    provider ? describeProvider(provider) : null,
    tier ? describeTier(tier) : null,
  ]
    .filter((part): part is string => Boolean(part))
    .join(" · ");
  return {
    name,
    recorded: Boolean(path || tier || provider || model),
    path: describePath(path),
    tier: describeTier(tier),
    provider: describeProvider(provider),
    model: model ?? NOT_RECORDED,
    detail: detail || NOT_RECORDED,
  };
}

function describeTarget(target?: RoutingTarget | null): string {
  if (!target) return NOT_RECORDED;
  const parts = [
    text(target.path) ? describePath(target.path) : null,
    text(target.model),
    text(target.tier) ? describeTier(target.tier) : null,
  ].filter((part): part is string => Boolean(part));
  return parts.length > 0 ? parts.join(" · ") : NOT_RECORDED;
}

function money(value: unknown): string {
  if (typeof value !== "number" || Number.isNaN(value)) return NOT_RECORDED;
  if (value === 0) return "$0.00";
  const digits = Math.abs(value) < 0.001 ? 6 : Math.abs(value) < 1 ? 4 : 2;
  return `$${value.toFixed(digits)}`;
}

function isPaidPath(path: unknown): boolean {
  return path === "cursor_sdk" || path === "external_model";
}

function targetsDiffer(
  first?: RoutingTarget | null,
  second?: RoutingTarget | null,
): boolean {
  const pairs: Array<[unknown, unknown]> = [
    [text(first?.path), text(second?.path)],
    [text(first?.provider), text(second?.provider)],
    [text(first?.model), text(second?.model)],
  ];
  return pairs.some(([left, right]) => left !== null && right !== null && left !== right);
}

function alternativeViews(
  alternatives: RoutingAlternative[] | null | undefined,
): RoutingAlternativeView[] {
  if (!Array.isArray(alternatives)) return [];
  return alternatives.map((alternative) => ({
    kind: alternative.kind,
    label: ALTERNATIVE_COPY[alternative.kind] ?? alternative.kind,
    target: describeTarget(alternative.target),
    reasons: (alternative.reason_codes ?? [])
      .map((code) => REASON_COPY[code] ?? code)
      .filter((reason): reason is string => Boolean(reason)),
  }));
}

function buildWarnings(routing: RoutingDecisionReceipt): RoutingWarningView[] {
  const warnings: RoutingWarningView[] = [];
  const recommended = routing.recommended ?? null;
  const selected = routing.selected ?? null;
  const executed = routing.executed ?? null;

  if (targetsDiffer(recommended, selected)) {
    warnings.push({
      tone: "warning",
      text: `The selected route (${describeTarget(selected)}) differs from the recommended route (${describeTarget(recommended)}).`,
    });
    if (isPaidPath(selected?.path) && recommended?.path === "local_ollama") {
      warnings.push({
        tone: "warning",
        text: "The selected path is more expensive than the recommendation for this task. A local model was enough.",
      });
    }
  }
  if (targetsDiffer(selected, executed)) {
    warnings.push({
      tone: "warning",
      text: `The executed route (${describeTarget(executed)}) differs from the selected route (${describeTarget(selected)}).`,
    });
  }
  if (executed?.path === "semantic_cache") {
    warnings.push({
      tone: "info",
      text: "No model was executed. The answer was reused from the semantic cache.",
    });
  }
  if (executed?.path === "no_execution") {
    warnings.push({
      tone: "info",
      text: "No model was executed for this request, so no provider or model is reported.",
    });
  }
  return warnings;
}

export function buildRoutingView(
  routing: RoutingDecisionReceipt | null | undefined,
): RoutingTransparencyView | null {
  if (!routing || typeof routing !== "object") return null;

  const basisKey = text(routing.basis) ?? "";
  const confidenceValue = routing.confidence?.value;
  const confidence =
    typeof confidenceValue === "number" && !Number.isNaN(confidenceValue)
      ? `${Math.round(confidenceValue * 100)}% (not calibrated)`
      : `${NOT_RECORDED} (not calibrated)`;
  const cost = routing.cost_efficiency ?? {};
  const costCode = text(cost.code) ?? "";
  const fingerprints = routing.fingerprints ?? {};

  return {
    version: text(routing.version) ?? "routing_receipt_v1",
    stages: [
      stageView("Recommended", routing.recommended),
      stageView("Selected", routing.selected),
      stageView("Executed", routing.executed),
    ],
    basis: BASIS_COPY[basisKey] ?? (basisKey || NOT_RECORDED),
    basisDetail: BASIS_DETAIL[basisKey] ?? "",
    confidence,
    reasons: (routing.reason_codes ?? []).map((code) => REASON_COPY[code] ?? code),
    assumptions: (routing.assumptions ?? []).map(
      (code) => ASSUMPTION_COPY[code] ?? code,
    ),
    alternatives: alternativeViews(routing.alternatives),
    costHeadline: COST_COPY[costCode] ?? COST_COPY.cost_comparison_unavailable,
    costRows: [
      { label: "Premium baseline", value: money(cost.estimated_baseline_cost_usd) },
      { label: "Estimated selected cost", value: money(cost.estimated_selected_cost_usd) },
      { label: "Actual executed cost", value: money(cost.actual_executed_cost_usd) },
      { label: "Estimated saving", value: money(cost.estimated_savings_usd) },
    ],
    warnings: buildWarnings(routing),
    fingerprints: [
      { label: "Prompt", value: text(fingerprints.prompt) ?? NOT_RECORDED },
      { label: "Result", value: text(fingerprints.result) ?? NOT_RECORDED },
      { label: "Diff", value: text(fingerprints.diff) ?? NOT_RECORDED },
    ],
  };
}

/**
 * Merge the recommendation frozen before a Cursor run with the routing facts
 * reported after it. The pre-run recommendation is what the user actually saw,
 * so it wins for the recommended stage; everything else comes from the server.
 */
export function mergeCursorRouting(
  frozen: RoutingDecisionReceipt | null | undefined,
  server: RoutingDecisionReceipt | null | undefined,
): RoutingDecisionReceipt | null {
  if (!server) return frozen ?? null;
  if (!frozen?.recommended) return server;
  return { ...server, recommended: frozen.recommended };
}
