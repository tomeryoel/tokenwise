import type { PolicyMode, RunResponse } from "./types";

const WEBHOOK_URL =
  import.meta.env.VITE_N8N_WEBHOOK_URL ??
  "http://localhost:5678/webhook/tokenwise";

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
