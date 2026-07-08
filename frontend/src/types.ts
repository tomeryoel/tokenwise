export type PolicyMode = "conservative" | "balanced" | "aggressive";

export interface DecisionReceipt {
  guardrail_status: string;
  cache_status: string;
  selected_tier: string;
  estimated_tokens: number;
  estimated_cost: number;
  optimization_reason: string;
  cost_saved: number;
}

export interface RunResponse {
  answer: string;
  receipt: DecisionReceipt;
  /** True when the answer came from the temporary local mock, not n8n. */
  usedMock: boolean;
}
