export type PolicyMode = "conservative" | "balanced" | "aggressive";

export interface DecisionReceipt {
  guardrail_status: string;
  cache_status: string;
  cache_confidence?: number | null;
  cache_entry_id?: string | null;
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
  task_type?: string | null;
  complexity_score?: number | null;
  complexity_level?: string | null;
  compression_recommended?: boolean | null;
  compression_target_ratio?: number | null;
  compression_reason?: string | null;
  compression_risk?: string | null;
  fallback_tier?: string | null;
  estimated_baseline_cost?: number | null;
  estimated_optimized_cost?: number | null;
  decision_reasons?: string[] | null;
}

export interface RunResponse {
  answer: string;
  receipt: DecisionReceipt;
  /** True when the answer came from the temporary local mock, not n8n. */
  usedMock: boolean;
}
