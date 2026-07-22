import type { DecisionReceipt, PolicyMode, RunResponse } from "./types";

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
 * POST to the n8n webhook (Layer 2), which orchestrates the FastAPI services
 * and returns { answer, receipt }. Pipeline failures are surfaced to the UI;
 * the frontend never invents a replacement response.
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

  let res: Response;
  try {
    res = await fetch(WEBHOOK_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestPayload),
    });
  } catch (error) {
    console.error("TokenWise could not reach the n8n workflow.", error);
    throw new Error(
      "The TokenWise workflow could not be reached. Make sure the local services are running, then try again.",
    );
  }

  if (!res.ok) {
    throw new Error(httpFailureMessage(res.status));
  }

  let data: unknown;
  try {
    data = await res.json();
  } catch (error) {
    console.error("TokenWise received invalid JSON from n8n.", error);
    throw new Error(
      "The TokenWise workflow returned an unreadable response. Check the n8n workflow output, then try again.",
    );
  }

  // n8n may wrap the payload in an array; normalise both documented shapes.
  const responsePayload = Array.isArray(data) ? data[0] : data;
  if (!isRunResponsePayload(responsePayload)) {
    console.error("TokenWise received an incomplete response from n8n.", data);
    throw new Error(
      "The TokenWise workflow returned an incomplete response. It must include both an answer and a decision receipt.",
    );
  }

  return responsePayload;
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

function httpFailureMessage(status: number): string {
  if (status === 404) {
    return "The TokenWise workflow endpoint was not found (HTTP 404). Make sure the n8n workflow is imported and active, then try again.";
  }
  if ([502, 503, 504].includes(status)) {
    return `The TokenWise workflow is temporarily unavailable (HTTP ${status}). Make sure n8n and its services are running, then try again.`;
  }
  if (status === 500) {
    return "The TokenWise workflow failed or could not be reached (HTTP 500). Make sure n8n and its services are running, then check the n8n execution log and try again.";
  }
  return `The TokenWise workflow could not complete the request (HTTP ${status}). Check the n8n execution log, then try again.`;
}

function isRunResponsePayload(value: unknown): value is RunResponse {
  if (!isRecord(value) || typeof value.answer !== "string") return false;
  return isDecisionReceipt(value.receipt);
}

function isDecisionReceipt(value: unknown): value is DecisionReceipt {
  if (!isRecord(value)) return false;
  return (
    typeof value.guardrail_status === "string" &&
    typeof value.cache_status === "string" &&
    typeof value.selected_tier === "string" &&
    typeof value.estimated_tokens === "number" &&
    typeof value.estimated_cost === "number" &&
    typeof value.optimization_reason === "string" &&
    typeof value.cost_saved === "number"
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
