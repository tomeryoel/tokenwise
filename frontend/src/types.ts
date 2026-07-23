export type PolicyMode = "conservative" | "balanced" | "aggressive";
export type CodingTaskType =
  | "bug_investigation"
  | "bug_fix"
  | "feature_implementation"
  | "refactor"
  | "test_generation"
  | "code_review"
  | "architecture_design"
  | "documentation"
  | "coding_ideation"
  | "unknown";
export type WorkflowType =
  | "direct"
  | "plan"
  | "agent"
  | "debug"
  | "review"
  | "unknown";
export type CodingSessionStatus =
  | "active"
  | "succeeded"
  | "partially_succeeded"
  | "failed"
  | "abandoned"
  | "unverified";
export type VerificationType =
  | "tests"
  | "build"
  | "lint"
  | "type_check"
  | "static_analysis"
  | "user_acceptance"
  | "reviewer_assessment"
  | "offline_evaluator"
  | "connector_completion"
  | "rollback";
export type VerificationStatus =
  | "passed"
  | "failed"
  | "partial"
  | "skipped";

export interface AuthUser {
  id: string;
  organization_id: string;
  organization_name: string;
  email: string;
  display_name: string;
  role: "owner" | "admin" | "member";
  department_id: string;
  policy_mode: PolicyMode;
  can_manage: boolean;
}

export interface AuthState {
  setup_required: boolean;
  authenticated: boolean;
  user: AuthUser | null;
}

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
  coding_session?: CodingAttemptTracking | null;
}

export interface CodingContext {
  primary_language: string | null;
  repository_size: "small" | "medium" | "large" | "unknown";
  files_supplied: number;
  test_files_supplied: number;
  has_error_details: boolean;
  has_acceptance_criteria: boolean;
  has_relevant_tests: boolean;
  approximate_context_tokens: number;
  context_source: "manual" | "playground_attachment" | "connector";
  privacy_classification: "standard" | "sensitive" | "restricted";
}

export interface CodingAttemptTracking {
  session_id: string;
  tracking_status: "recorded" | "not_recorded" | "unavailable";
  attempt_id?: string | null;
  attempt_number?: number | null;
  reason?: string | null;
}

export interface CodingSession {
  session_id: string;
  organization_id: string;
  user_id: string;
  dept_id: string;
  policy_mode: PolicyMode;
  objective_fingerprint: string;
  predicted_task_type: CodingTaskType;
  confirmed_task_type: CodingTaskType | null;
  classification_confidence: number;
  classification_source: string;
  classification_reason: string;
  clarification_required: boolean;
  complexity_level: "low" | "medium" | "high" | null;
  status: CodingSessionStatus;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export type EvidenceConfidence =
  | "insufficient"
  | "low"
  | "medium"
  | "high";

export interface ModelFitComponents {
  outcome: number | null;
  quality: number | null;
  cost_efficiency: number | null;
  attempt_efficiency: number | null;
  policy: number | null;
}

export interface DecisionEvaluation {
  evaluation_id: string;
  evaluated_at: string;
  session_id: string;
  scoring_version: string;
  model_fit: {
    status: "unavailable" | "provisional" | "final";
    value: number | null;
    confidence: EvidenceConfidence;
    components: ModelFitComponents;
    missing_components: string[];
    evidence: string[];
    basis: string;
    reason: string;
  };
  cost_to_success: {
    cost_spent: number;
    cost_to_success: number | null;
    attempts_to_success: number | null;
    time_to_success_ms: number | null;
    cost_basis: "actual" | "modeled" | "mixed" | "unknown";
    local_compute_rate_version: string | null;
    currency: string;
    complete: boolean;
    missing_cost_fields: string[];
    reason: string;
  };
  fit_gap: {
    status: "unavailable" | "available";
    value: number | null;
    candidate_id: string | null;
    basis: string | null;
    reason: string;
  };
  power_classification: {
    status: "unavailable" | "appropriate" | "overpowered" | "underpowered";
    candidate_id: string | null;
    confidence: EvidenceConfidence;
    reason: string;
  };
  evidence_sources: string[];
}
