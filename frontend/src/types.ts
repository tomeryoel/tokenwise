export type PolicyMode = "conservative" | "balanced" | "aggressive";

export interface DecisionReceipt {
  guardrail_status: string;
  cache_status: string;
  selected_tier: string;
  estimated_tokens: number;
  estimated_cost: number;
  optimization_reason: string;
  cost_saved: number;
  detected_risk_type?: string | null;
  reason?: string | null;
  output_guardrail_status?: string | null;
  output_guardrail_issues?: string[] | null;
  savings_source?: string | null;
  savings_reason?: string | null;
}

export interface RunResponse {
  answer: string;
  receipt: DecisionReceipt;
  /** True when the answer came from the temporary local mock, not n8n. */
  usedMock: boolean;
}
