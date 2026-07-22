import type { PolicyMode, RunResponse } from "./types";

const WEBHOOK_URL =
  import.meta.env.VITE_N8N_WEBHOOK_URL ??
  "/api/webhook/tokenwise";

const USAGE_SUMMARY_URL =
  import.meta.env.VITE_USAGE_SUMMARY_URL ??
  "/api/webhook/tokenwise-usage-summary";

export interface UsageSummary {
  period_days: number;
  total_requests: number;
  completed_requests: number;
  blocked_requests: number;
  total_actual_cost: number;
  total_actual_api_cost: number;
  total_estimated_baseline_cost: number;
  total_estimated_optimized_cost: number;
  total_savings: number;
  total_modeled_cost_avoidance: number;
  cost_avoidance_basis: string;
  actual_cost_savings_request_count: number;
  estimated_savings_request_count: number;
  unknown_actual_cost_request_count: number;
  savings_percentage: number | null;
  operating_cost_usd: number | null;
  roi_percentage: number | null;
  roi_status: string;
  roi_basis: string;
  cache_hit_rate: number;
  guardrail_block_rate: number;
  premium_usage_rate: number;
  premium_requested_rate: number;
  fallback_rate: number;
  average_latency_ms: number;
  total_input_tokens: number;
  total_output_tokens: number;
  requests_by_source: Record<string, number>;
  savings_by_source: Record<string, number>;
  requests_by_policy_mode: Record<string, number>;
  savings_by_policy_mode: Record<string, number>;
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
async function fileToBase64(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

export async function runPrompt(
  prompt: string,
  policyMode: PolicyMode,
  attachment?: File | null,
): Promise<RunResponse> {
  const requestPayload: Record<string, unknown> = {
    prompt,
    policy_mode: policyMode,
  };
  if (attachment) {
    requestPayload.has_image = true;
    requestPayload.image_filename = attachment.name;
    requestPayload.image_base64 = await fileToBase64(attachment);
  }

  try {
    const res = await fetch(WEBHOOK_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestPayload),
    });
    if (!res.ok) throw new Error(`n8n returned ${res.status}`);
    const data = await res.json();
    // n8n may wrap the payload in an array; normalise both shapes.
    const responsePayload = Array.isArray(data) ? data[0] : data;
    return {
      answer: responsePayload.answer ?? "(no answer field returned)",
      receipt: responsePayload.receipt,
      usedMock: false,
    };
  } catch (error) {
    console.error("TokenWise request failed; using frontend mock.", error);
    return temporaryMock(prompt, policyMode);
  }
}

export async function fetchUsageSummary(
  deptId?: string,
  periodDays = 30,
  operatingCostUsd?: number,
): Promise<UsageSummary> {
  const params = new URLSearchParams({ period_days: String(periodDays) });
  if (deptId) params.set("dept_id", deptId);
  if (operatingCostUsd != null) {
    params.set("operating_cost_usd", String(operatingCostUsd));
  }
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
