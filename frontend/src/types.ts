export type PolicyMode = "conservative" | "balanced" | "aggressive";

export interface DecisionReceipt {
  policy_mode?: PolicyMode | null;
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
  graph_path?: string | null;
  branch_reason?: string | null;
  executed_nodes?: string[] | null;
  provider?: string | null;
  model?: string | null;
  requested_tier?: string | null;
  executed_tier?: string | null;
  actual_input_tokens?: number | null;
  actual_output_tokens?: number | null;
  actual_total_tokens?: number | null;
  actual_cost?: number | null;
  actual_cost_saved?: number | null;
  latency_ms?: number | null;
  used_fallback?: boolean | null;
  fallback_reason?: string | null;
  privacy_enforced?: boolean | null;
  cost_calculation_status?: string | null;
  actual_execution_attempt_count?: number | null;
  prompt_redaction_applied?: boolean | null;
  provider_attempts?: string[] | null;
  error_code?: string | null;
  has_image?: boolean | null;
  image_class?: string | null;
  image_filename?: string | null;
  image_confidence?: number | null;
  visual_complexity?: number | null;
  needs_vision_model?: boolean | null;
}

export interface RunResponse {
  answer: string;
  receipt: DecisionReceipt;
}
