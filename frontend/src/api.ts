import type { PolicyMode, RunResponse } from "./types";

const WEBHOOK_URL =
  import.meta.env.VITE_N8N_WEBHOOK_URL ??
  "http://localhost:5678/webhook/tokenwise";

const USAGE_SUMMARY_URL =
  import.meta.env.VITE_USAGE_SUMMARY_URL ??
  "http://localhost:5679/webhook/tokenwise-usage-summary";

export interface UsageSummary {
  period_days: number;
  total_requests: number;
  completed_requests: number;
  blocked_requests: number;
  total_actual_cost: number;
  total_estimated_baseline_cost: number;
  total_savings: number;
  savings_percentage: number | null;
  roi_percentage: number | null;
  roi_status: string;
  cache_hit_rate: number;
  guardrail_block_rate: number;
  premium_usage_rate: number;
  fallback_rate: number;
  average_latency_ms: number;
  total_input_tokens: number;
  total_output_tokens: number;
  requests_by_source: Record<string, number>;
  savings_by_source: Record<string, number>;
}

/**
 * Send a prompt through the TokenWise pipeline.
 *
 * Primary path: POST to the n8n webhook (Layer 2), which orchestrates the
 * FastAPI services and returns { answer, receipt }.
 *
 * Fallback path (TEMPORARY): if n8n is not reachable / workflow not imported,
 * we return a clearly-labelled local mock so the UI is still demonstrable.
 * Remove the fallback once the n8n workflow is reliably running.
 */
export async function runPrompt(
  prompt: string,
  policyMode: PolicyMode,
): Promise<RunResponse> {
  try {
    const res = await fetch(WEBHOOK_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, policy_mode: policyMode }),
    });
    if (!res.ok) throw new Error(`n8n returned ${res.status}`);
    const data = await res.json();
    // n8n may wrap the payload in an array; normalise both shapes.
    const payload = Array.isArray(data) ? data[0] : data;
    return {
      answer: payload.answer ?? "(no answer field returned)",
      receipt: payload.receipt,
      usedMock: false,
    };
  } catch {
    return temporaryMock(prompt, policyMode);
  }
}

export async function fetchUsageSummary(
  deptId?: string,
  periodDays = 30,
): Promise<UsageSummary> {
  const params = new URLSearchParams({ period_days: String(periodDays) });
  if (deptId) params.set("dept_id", deptId);
  const res = await fetch(`${USAGE_SUMMARY_URL}?${params.toString()}`);
  if (!res.ok) throw new Error(`usage summary returned ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// TEMPORARY MOCK - remove when n8n webhook is stable.
// ---------------------------------------------------------------------------
function temporaryMock(prompt: string, policyMode: PolicyMode): RunResponse {
  const estimated_tokens = Math.max(1, Math.round(prompt.length / 4));
  const tier =
    policyMode === "aggressive"
      ? "cheap"
      : policyMode === "conservative"
        ? "balanced"
        : estimated_tokens < 200
          ? "cheap"
          : "balanced";
  const tierPrice: Record<string, number> = {
    cheap: 0.0005,
    balanced: 0.003,
  };
  const estimated_cost = Number(
    ((estimated_tokens / 1000) * (tierPrice[tier] ?? 0.0005)).toFixed(6),
  );
  const baseline = Number(((estimated_tokens / 1000) * 0.03).toFixed(6));
  return {
    answer:
      "[LOCAL MOCK] TokenWise skeleton response. n8n webhook was not reachable, " +
      "so this came from the temporary frontend mock.",
    receipt: {
      guardrail_status: "passed",
      cache_status: "miss",
      selected_tier: tier,
      estimated_tokens,
      estimated_cost,
      optimization_reason: `[FRONTEND MOCK] policy_mode=${policyMode} -> ${tier} tier`,
      cost_saved: Number(Math.max(0, baseline - estimated_cost).toFixed(6)),
    },
    usedMock: true,
  };
}
