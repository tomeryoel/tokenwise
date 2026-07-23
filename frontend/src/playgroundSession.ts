import type {
  CodingContext,
  CodingSession,
  CodingTaskType,
  DecisionEvaluation,
  RunResponse,
  WorkflowType,
} from "./types";

export type PlaygroundMode = "coding" | "quick";
export type CodingPhase =
  | "draft"
  | "review"
  | "awaiting_verification"
  | "continuing"
  | "evaluated";

export const initialCodingContext = (): CodingContext => ({
  primary_language: null,
  repository_size: "unknown",
  files_supplied: 0,
  test_files_supplied: 0,
  has_error_details: false,
  has_acceptance_criteria: false,
  has_relevant_tests: false,
  approximate_context_tokens: 0,
  context_source: "manual",
  privacy_classification: "standard",
});

/** In-memory Playground session (not persisted to browser storage). */
export interface PlaygroundSession {
  prompt: string;
  loading: boolean;
  result: RunResponse | null;
  error: string | null;
  attachment: File | null;
  submittedPrompt: string | null;
  submittedAttachmentName: string | null;
  mode: PlaygroundMode;
  codingPhase: CodingPhase;
  codingSession: CodingSession | null;
  selectedTaskType: CodingTaskType;
  workflow: WorkflowType;
  codingContext: CodingContext;
  evaluation: DecisionEvaluation | null;
  verificationLoading: boolean;
  verificationError: string | null;
}

export const initialPlaygroundSession = (): PlaygroundSession => ({
  prompt: "",
  loading: false,
  result: null,
  error: null,
  attachment: null,
  submittedPrompt: null,
  submittedAttachmentName: null,
  mode: "coding",
  codingPhase: "draft",
  codingSession: null,
  selectedTaskType: "unknown",
  workflow: "plan",
  codingContext: initialCodingContext(),
  evaluation: null,
  verificationLoading: false,
  verificationError: null,
});
