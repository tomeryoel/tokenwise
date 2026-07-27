import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import ReactMarkdown from "react-markdown";
import {
  createCodingSession,
  fetchCodingEvaluation,
  fetchCursorAgentHealth,
  fetchCursorAgentModels,
  recommendCursorRoute,
  recordVerification,
  runCursorAgent,
  runPrompt,
  updateCodingSession,
} from "../api";
import { PRODUCT_NAME } from "../brand";
import DecisionReceipt from "../components/DecisionReceipt";
import ModelFitReceipt from "../components/ModelFitReceipt";
import RoutingTransparencyBlock from "../components/RoutingTransparencyBlock";
import { mergeCursorRouting } from "../routingTransparency";
import VerificationPanel, {
  type VerificationSubmission,
} from "../components/VerificationPanel";
import {
  initialPlaygroundSession,
  type PlaygroundMode,
  type PlaygroundSession,
} from "../playgroundSession";
import type {
  CodingContext,
  CodingTaskType,
  PolicyMode,
  WorkflowType,
} from "../types";

interface Props {
  policyMode: PolicyMode;
  session: PlaygroundSession;
  setSession: React.Dispatch<React.SetStateAction<PlaygroundSession>>;
}

function cursorAgentRunErrorMessage(
  status: string,
  detail: string | null | undefined,
): string {
  switch (status) {
    case "blocked_dirty_worktree":
      return "This run was blocked because the Git worktree is dirty. Reset the disposable sandbox, then try again.";
    case "blocked_validation":
      return "That validation command is not allowlisted. Choose an approved command, then try again.";
    case "blocked_preflight":
      return "This run was blocked by workspace safety checks. Use the disposable sandbox, then try again.";
    case "bridge_error":
      return detail?.includes("cursor_api_key")
        ? "Cursor authentication is missing or invalid. Configure the bridge API key, then retry."
        : detail || "The Cursor SDK bridge could not start this run. Please try again.";
    default:
      return (
        detail ||
        `Cursor Agent Coding Run finished with status ${status}. Your draft was preserved.`
      );
  }
}

const TASK_TYPES: { value: CodingTaskType; label: string }[] = [
  { value: "bug_investigation", label: "Bug investigation" },
  { value: "bug_fix", label: "Bug fix" },
  { value: "feature_implementation", label: "Feature implementation" },
  { value: "refactor", label: "Refactor" },
  { value: "test_generation", label: "Test generation" },
  { value: "code_review", label: "Code review" },
  { value: "architecture_design", label: "Architecture design" },
  { value: "documentation", label: "Documentation" },
  { value: "coding_ideation", label: "Coding ideation" },
  { value: "unknown", label: "Needs clarification" },
];

const WORKFLOWS: { value: WorkflowType; label: string; detail: string }[] = [
  { value: "plan", label: "Plan", detail: "Reason about the approach first" },
  { value: "debug", label: "Debug", detail: "Investigate evidence step by step" },
  { value: "direct", label: "Direct", detail: "Answer without a planning phase" },
  { value: "agent", label: "Agent", detail: "Multi-step autonomous workflow" },
  { value: "review", label: "Review", detail: "Inspect and critique existing work" },
  { value: "unknown", label: "Not specified", detail: "No workflow signal" },
];

export default function Playground({
  policyMode,
  session,
  setSession,
}: Props) {
  const {
    prompt,
    loading,
    result,
    error,
    attachment,
    submittedPrompt,
    submittedAttachmentName,
    mode,
    codingPhase,
    codingSession,
    selectedTaskType,
    workflow,
    codingContext,
    evaluation,
    verificationLoading,
    verificationError,
    cursorSelectedModel,
    cursorRecommendedModel,
    cursorRecommendationReasons,
    cursorRecommendedPath,
    cursorPathReasons,
    cursorRecommendationBasis,
    cursorRecommendationConfidence,
    cursorRoutingRecommendation,
    cursorModels,
    cursorBridgeStatus,
    cursorValidationCommand,
    cursorAgentResult,
  } = session;
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const resultRef = useRef<HTMLElement>(null);
  const verificationRef = useRef<HTMLDivElement>(null);
  const evaluationRef = useRef<HTMLDivElement>(null);
  const previousResultRef = useRef(result);
  const [announcement, setAnnouncement] = useState("");
  const hasDraft = Boolean(prompt.trim() || attachment);
  const reviewingClassification =
    mode === "coding" && codingPhase === "review" && codingSession !== null;
  const continuingSession =
    mode === "coding" && codingPhase === "continuing" && codingSession !== null;
  const resultIsPrevious = Boolean(
    result && (loading || error || hasDraft || continuingSession),
  );
  const tracking = result?.coding_session ?? null;
  const canVerify =
    mode === "coding" &&
    codingPhase === "awaiting_verification" &&
    tracking?.tracking_status === "recorded" &&
    Boolean(tracking.attempt_id);
  const composerLocked =
    mode === "coding" &&
    ["review", "awaiting_verification", "evaluated"].includes(codingPhase);
  const submissionLocked =
    mode === "coding" &&
    ["awaiting_verification", "evaluated"].includes(codingPhase);

  useEffect(() => {
    if (result && result !== previousResultRef.current && !error) {
      const reduceMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
      ).matches;
      window.requestAnimationFrame(() => {
        resultRef.current?.scrollIntoView({
          behavior: reduceMotion ? "auto" : "smooth",
          block: "start",
        });
        resultRef.current?.focus({ preventScroll: true });
      });
    }
    previousResultRef.current = result;
  }, [error, result]);

  async function handleSubmit(event?: FormEvent) {
    event?.preventDefault();
    if (loading) return;
    if (!prompt.trim() && !attachment) return;

    if (mode === "cursor_agent") {
      await executeCursorAgent();
      return;
    }
    if (mode === "coding" && codingPhase === "draft") {
      await classifyObjective();
      return;
    }
    await executeRequest();
  }

  async function prepareCursorAgentMode() {
    try {
      const [health, modelsPayload] = await Promise.all([
        fetchCursorAgentHealth(),
        fetchCursorAgentModels(),
      ]);
      setSession((current) => ({
        ...current,
        cursorBridgeStatus: health.status,
        cursorModels: modelsPayload.models.map((model) => ({
          id: model.id,
          display_name: model.display_name,
        })),
        cursorSelectedModel:
          current.cursorSelectedModel ||
          modelsPayload.models[0]?.id ||
          "",
        error:
          health.status === "ok"
            ? null
            : health.detail ||
              "The Cursor SDK bridge is not ready. Start the bridge, then try again.",
      }));
    } catch (requestError) {
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Could not reach Cursor Agent Coding Run.";
      setSession((current) => ({
        ...current,
        cursorBridgeStatus: "unavailable",
        error: message,
      }));
    }
  }

  async function refreshCursorRecommendation() {
    const objective = prompt.trim();
    if (!objective) return;
    try {
      const recommendation = await recommendCursorRoute({
        objective,
        workflow: "agent",
      });
      setSession((current) => ({
        ...current,
        cursorRecommendedModel: recommendation.recommended_model_id,
        cursorRecommendationReasons: recommendation.reasons,
        cursorRecommendedPath: recommendation.recommended_path ?? null,
        cursorPathReasons: recommendation.path_reasons ?? [],
        cursorRecommendationBasis: recommendation.recommendation_basis ?? null,
        cursorRecommendationConfidence:
          typeof recommendation.confidence === "number"
            ? recommendation.confidence
            : null,
        cursorRoutingRecommendation: recommendation.routing ?? null,
        cursorSelectedModel:
          current.cursorSelectedModel || recommendation.recommended_model_id,
        error: null,
      }));
    } catch (requestError) {
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Could not refresh the model recommendation.";
      setSession((current) => ({
        ...current,
        error: message,
      }));
    }
  }

  async function executeCursorAgent() {
    const requestPrompt = prompt.trim();
    if (!requestPrompt) return;
    if (!cursorSelectedModel) {
      setSession((current) => ({
        ...current,
        error: "Select a Cursor model before running Cursor Agent Coding Run.",
      }));
      return;
    }
    if (cursorBridgeStatus && cursorBridgeStatus !== "ok") {
      setSession((current) => ({
        ...current,
        error:
          "The Cursor SDK bridge is not ready. Recheck the bridge, then try again.",
      }));
      return;
    }

    setSession((current) => ({
      ...current,
      loading: true,
      error: null,
      cursorAgentResult: null,
    }));
    setAnnouncement("Running Cursor Agent Coding Run through the local SDK bridge.");

    try {
      if (!cursorRecommendedModel) {
        await refreshCursorRecommendation();
      }
      const response = await runCursorAgent({
        prompt: requestPrompt,
        selected_model: cursorSelectedModel,
        recommended_model: cursorRecommendedModel,
        workflow: "agent",
        validation_command: cursorValidationCommand || null,
        include_diff_in_response: true,
      });
      const validationFailed = response.validation_status === "failed";
      const validationTimedOut = response.validation_status === "timed_out";
      setSession((current) => ({
        ...current,
        loading: false,
        submittedPrompt: requestPrompt,
        cursorAgentResult: {
          // The recommendation the user saw before the run stays authoritative
          // for the recommended stage; the server supplies the run facts.
          routing: mergeCursorRouting(
            current.cursorRoutingRecommendation,
            response.receipt?.routing ?? null,
          ),
          answer: response.answer,
          status: response.status,
          model_used: response.model_used,
          selected_model: response.selected_model,
          recommended_model: response.recommended_model,
          sdk_run_id: response.sdk_run_id,
          session_id: response.session_id,
          attempt_id: response.attempt_id,
          result_fingerprint: response.result_fingerprint,
          claim: response.claim,
          error: response.error,
          workspace_cwd: response.workspace_cwd ?? null,
          workspace_kind: response.workspace_kind ?? null,
          sdk_sandbox_enabled: response.sdk_sandbox_enabled ?? null,
          changed_files: response.changed_files ?? [],
          diff_text: response.diff_text ?? null,
          diff_fingerprint: response.diff_fingerprint ?? null,
          diff_truncated: Boolean(response.diff_truncated),
          validation_command: response.validation_command ?? null,
          validation_status: response.validation_status ?? null,
          validation_exit_code: response.validation_exit_code ?? null,
          validation_stdout: response.validation_stdout ?? null,
          validation_stderr: response.validation_stderr ?? null,
        },
        error:
          response.status === "finished"
            ? validationFailed
              ? "Cursor Agent Coding Run finished, but validation failed. Review the Validation section below."
              : validationTimedOut
                ? "Cursor Agent Coding Run finished, but validation timed out. Review the Validation section below."
                : null
            : cursorAgentRunErrorMessage(response.status, response.error),
      }));
      setAnnouncement(
        response.status === "finished" && !validationFailed && !validationTimedOut
          ? "Cursor Agent Coding Run result is ready in MomiHelm."
          : "Cursor Agent Coding Run needs attention before you continue.",
      );
    } catch (requestError) {
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Cursor Agent Coding Run failed";
      setSession((current) => ({
        ...current,
        loading: false,
        error: message,
      }));
      setAnnouncement("Cursor Agent Coding Run could not complete. Your draft was preserved.");
    }
  }

  async function classifyObjective() {
    const objective = prompt.trim();
    if (!objective) return;
    setSession((current) => ({
      ...current,
      loading: true,
      error: null,
      verificationError: null,
    }));
    setAnnouncement(`${PRODUCT_NAME} is classifying the coding objective.`);
    try {
      const created = await createCodingSession(objective);
      setSession((current) => ({
        ...current,
        loading: false,
        codingSession: created,
        selectedTaskType: created.predicted_task_type,
        codingPhase: "review",
        error: null,
      }));
      setAnnouncement(
        `${PRODUCT_NAME} classified the objective. Review the coding session before running it.`,
      );
    } catch (requestError) {
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Classification failed";
      setSession((current) => ({
        ...current,
        loading: false,
        error: message,
      }));
      setAnnouncement(
        `${PRODUCT_NAME} could not classify the objective. Your draft was preserved.`,
      );
    }
  }

  async function executeRequest() {
    const requestPrompt = prompt.trim();
    const requestAttachment = attachment;
    if (!requestPrompt && !requestAttachment) return;
    if (mode === "coding" && !codingSession) return;

    setSession((current) => ({
      ...current,
      loading: true,
      error: null,
      verificationError: null,
    }));
    setAnnouncement(`${PRODUCT_NAME} is working on your request.`);

    try {
      let activeCodingSession = codingSession;
      if (
        mode === "coding" &&
        activeCodingSession &&
        activeCodingSession.confirmed_task_type !== selectedTaskType
      ) {
        activeCodingSession = await updateCodingSession(
          activeCodingSession.session_id,
          { confirmed_task_type: selectedTaskType },
        );
      }

      const response = await runPrompt(
        requestPrompt,
        requestAttachment,
        mode === "coding" && activeCodingSession
          ? {
              session_id: activeCodingSession.session_id,
              recommended_workflow: workflow,
              executed_workflow: workflow,
              context: {
                ...codingContext,
                context_source: requestAttachment
                  ? "playground_attachment"
                  : "manual",
              },
            }
          : null,
      );
      const recorded =
        response.coding_session?.tracking_status === "recorded" &&
        Boolean(response.coding_session.attempt_id);
      setSession((current) => ({
        ...current,
        prompt: "",
        loading: false,
        result: response,
        error: null,
        attachment: null,
        submittedPrompt: requestPrompt,
        submittedAttachmentName: requestAttachment?.name ?? null,
        codingSession: activeCodingSession,
        codingPhase:
          mode === "coding"
            ? recorded
              ? "awaiting_verification"
              : "continuing"
            : "draft",
        evaluation: null,
      }));
      if (fileInputRef.current) fileInputRef.current.value = "";
      setAnnouncement(
        mode === "coding" && recorded
          ? `${PRODUCT_NAME}'s answer is ready for outcome verification.`
          : `${PRODUCT_NAME}'s answer is ready.`,
      );
    } catch (requestError) {
      const message =
        requestError instanceof Error ? requestError.message : "Request failed";
      setSession((current) => ({
        ...current,
        loading: false,
        error: message,
      }));
      setAnnouncement(
        `${PRODUCT_NAME} could not complete the request. Your draft was preserved.`,
      );
    }
  }

  async function handleVerification(submission: VerificationSubmission) {
    if (
      !codingSession ||
      !tracking?.attempt_id ||
      tracking.tracking_status !== "recorded"
    ) {
      return;
    }
    setSession((current) => ({
      ...current,
      verificationLoading: true,
      verificationError: null,
    }));

    try {
      for (const check of submission.checks) {
        await recordVerification(codingSession.session_id, {
          attempt_id: tracking.attempt_id,
          verification_type: check.verification_type,
          status: check.status,
          details: submission.details,
        });
      }

      const acceptanceStatus =
        submission.outcome === "succeeded"
          ? "passed"
          : submission.outcome === "partially_succeeded"
            ? "partial"
            : "failed";
      await recordVerification(codingSession.session_id, {
        attempt_id: tracking.attempt_id,
        verification_type: "user_acceptance",
        status: acceptanceStatus,
        details: submission.details,
      });

      if (submission.outcome === "retry") {
        setSession((current) => ({
          ...current,
          verificationLoading: false,
          verificationError: null,
          codingPhase: "continuing",
        }));
        setAnnouncement(
          "Outcome recorded. The next prompt will remain in this coding session.",
        );
        window.requestAnimationFrame(() => focusComposer());
        return;
      }

      const status =
        submission.outcome === "succeeded"
          ? "succeeded"
          : submission.outcome === "partially_succeeded"
            ? "partially_succeeded"
            : "failed";
      const updated = await updateCodingSession(codingSession.session_id, {
        status,
      });
      const decisionEvaluation = await fetchCodingEvaluation(
        codingSession.session_id,
      );
      setSession((current) => ({
        ...current,
        verificationLoading: false,
        verificationError: null,
        codingSession: updated,
        codingPhase: "evaluated",
        evaluation: decisionEvaluation,
      }));
      setAnnouncement(
        `${PRODUCT_NAME} calculated an evidence-labeled Model Fit assessment.`,
      );
    } catch (requestError) {
      const message =
        requestError instanceof Error
          ? requestError.message
          : "Verification failed";
      setSession((current) => ({
        ...current,
        verificationLoading: false,
        verificationError: message,
      }));
    }
  }

  function handlePromptKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) return;
    if (event.nativeEvent.isComposing) return;
    event.preventDefault();
    void handleSubmit();
  }

  function handleFileChange(file: File | null) {
    setSession((current) => ({
      ...current,
      attachment: file,
      error: null,
    }));
  }

  function removeAttachment() {
    if (fileInputRef.current) fileInputRef.current.value = "";
    setSession((current) => ({
      ...current,
      attachment: null,
      error: null,
    }));
  }

  function setMode(nextMode: PlaygroundMode) {
    if (loading || (codingSession && codingPhase !== "evaluated")) return;
    const fresh = initialPlaygroundSession();
    setSession({
      ...fresh,
      mode: nextMode,
      prompt,
    });
    setAnnouncement(
      nextMode === "coding"
        ? "Coding-session mode is ready."
        : nextMode === "cursor_agent"
          ? "Cursor Agent Coding Run is ready."
          : "Quick-question mode is ready.",
    );
    if (nextMode === "cursor_agent") {
      void prepareCursorAgentMode();
      if (prompt.trim()) {
        void refreshCursorRecommendation();
      }
    }
  }

  const primaryAction =
    mode === "quick"
      ? `Ask ${PRODUCT_NAME}`
      : mode === "cursor_agent"
        ? "Run Cursor Agent Coding Run"
        : codingPhase === "draft"
          ? "Review coding objective"
          : codingPhase === "review"
            ? "Run coding attempt"
            : codingPhase === "awaiting_verification"
              ? "Verify current attempt below"
              : codingPhase === "evaluated"
                ? "Session evaluated"
                : "Run next attempt";


  function updateContext(changes: Partial<CodingContext>) {
    setSession((current) => ({
      ...current,
      codingContext: { ...current.codingContext, ...changes },
    }));
  }

  function editObjective() {
    setSession((current) => ({
      ...current,
      codingSession: null,
      codingPhase: "draft",
      selectedTaskType: "unknown",
      evaluation: null,
      error: null,
    }));
    setAnnouncement("Edit the coding objective and classify it again.");
    window.requestAnimationFrame(() => promptRef.current?.focus());
  }

  function startNewCodingSession() {
    setSession(initialPlaygroundSession());
    setAnnouncement("A new coding session is ready.");
    window.requestAnimationFrame(() => promptRef.current?.focus());
  }

  function focusComposer() {
    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    promptRef.current?.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "center",
    });
    promptRef.current?.focus({ preventScroll: true });
  }

  function focusOutcomeAction() {
    if (evaluation) {
      evaluationRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
      return;
    }
    if (canVerify) {
      verificationRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
      return;
    }
    focusComposer();
  }

  return (
    <div className="page playground-page">
      <header className="playground-header">
        <div>
          <span className="page-eyebrow">AI coding decision intelligence</span>
          <h1>Playground</h1>
          <p>
            Run a verified coding session to measure Model Fit and
            Cost-to-Success, use Quick question for the lightweight path, or run
            Cursor Agent Coding Run with model selection, diff review, and
            validation.
          </p>
        </div>
      </header>

      <div className="workspace-mode-switch" aria-label="Playground mode">
        <button
          type="button"
          className={mode === "coding" ? "active" : ""}
          disabled={Boolean(codingSession && codingPhase !== "evaluated")}
          onClick={() => setMode("coding")}
        >
          <span>Coding session</span>
          <small>Classify, route, verify, and evaluate</small>
        </button>
        <button
          type="button"
          className={mode === "quick" ? "active" : ""}
          disabled={Boolean(codingSession && codingPhase !== "evaluated")}
          onClick={() => setMode("quick")}
        >
          <span>Quick question</span>
          <small>Ask without outcome tracking</small>
        </button>
        <button
          type="button"
          className={mode === "cursor_agent" ? "active" : ""}
          disabled={Boolean(codingSession && codingPhase !== "evaluated")}
          onClick={() => setMode("cursor_agent")}
        >
          <span>Cursor Agent Coding Run</span>
          <small>
            Execute repository tasks safely with model selection, diff review,
            and validation.
          </small>
        </button>
      </div>

      {continuingSession && (
        <div className="continuing-session-banner">
          <span>Continuing coding session</span>
          <strong>
            Attempt {(result?.coding_session?.attempt_number ?? 0) + 1}
          </strong>
          <small>
            The next response will contribute to the same Cost-to-Success.
          </small>
        </div>
      )}

      <form
        className="playground-composer"
        onSubmit={handleSubmit}
        aria-busy={loading}
      >
        <label className="field-label" htmlFor="playground-prompt">
          {mode === "coding"
            ? continuingSession
              ? "What should MomiHelm try next?"
              : "What coding objective should MomiHelm help complete?"
            : mode === "cursor_agent"
              ? "What coding change should the Cursor Agent make in the sandbox?"
              : "What would you like help with?"}
        </label>
        <textarea
          ref={promptRef}
          id="playground-prompt"
          className="prompt"
          rows={6}
          placeholder={
            mode === "coding"
              ? "Describe the bug, feature, review, tests, or coding outcome you need..."
              : mode === "cursor_agent"
                ? "Example: Update hello.py so greet() returns a personalized greeting, then keep tests green."
              : "Ask a question, analyze an idea, or request help..."
          }
          value={prompt}
          disabled={loading || composerLocked}
          aria-describedby="playground-keyboard-hint"
          onChange={(event) =>
            setSession((current) => ({
              ...current,
              prompt: event.target.value,
              error: null,
            }))
          }
          onBlur={() => {
            if (mode === "cursor_agent" && prompt.trim()) {
              void refreshCursorRecommendation();
            }
          }}
          onKeyDown={handlePromptKeyDown}
        />

        {mode === "cursor_agent" && (
          <section
            className="cursor-agent-panel"
            aria-label="Cursor Agent Coding Run controls"
          >
            <div className="continuing-session-banner">
              <span>Cursor SDK</span>
              <strong>Cursor Agent Coding Run via official Cursor SDK</strong>
              <small>
                Uses the disposable local sandbox by default. Dirty Git
                worktrees are hard-blocked. Raw diffs are shown for this run only
                and are not persisted. Bridge status:{" "}
                {cursorBridgeStatus ?? "unknown"}
                {cursorBridgeStatus === "ok"
                  ? " (reachable; Cursor API auth is confirmed on model list or run)."
                  : "."}
              </small>
            </div>

            <div className="coding-setup-grid">
              <label>
                Recommended model
                <input
                  type="text"
                  value={cursorRecommendedModel || "Not recommended yet"}
                  readOnly
                />
              </label>
              <label>
                Selected Cursor model
                <select
                  value={cursorSelectedModel}
                  disabled={loading || cursorModels.length === 0}
                  onChange={(event) =>
                    setSession((current) => ({
                      ...current,
                      cursorSelectedModel: event.target.value,
                    }))
                  }
                >
                  {cursorModels.length === 0 ? (
                    <option value="">No models available</option>
                  ) : (
                    cursorModels.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.display_name} ({model.id})
                      </option>
                    ))
                  )}
                </select>
              </label>
              <label>
                Validation command (allowlisted)
                <select
                  value={cursorValidationCommand}
                  disabled={loading}
                  onChange={(event) =>
                    setSession((current) => ({
                      ...current,
                      cursorValidationCommand: event.target.value,
                    }))
                  }
                >
                  <option value="">No validation</option>
                  <option value="python3 -m pytest">python3 -m pytest</option>
                  <option value="python -m pytest">python -m pytest</option>
                  <option value="pytest">pytest</option>
                  <option value="npm test">npm test</option>
                  <option value="npm run test">npm run test</option>
                  <option value="npm run lint">npm run lint</option>
                </select>
              </label>
            </div>

            {cursorRecommendationReasons.length > 0 && (
              <ul className="muted-list">
                {cursorRecommendationReasons.slice(0, 3).map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            )}

            {cursorRecommendedPath && (
              <div className="continuing-session-banner">
                <span>Cost-efficient path (heuristic)</span>
                <strong>
                  {cursorRecommendedPath === "local_ollama"
                    ? "Prefer local Ollama via Quick Question / Coding Session"
                    : "Prefer Cursor SDK Coding Run"}
                </strong>
                <small>
                  Basis: {cursorRecommendationBasis ?? "heuristic"}
                  {cursorRecommendationConfidence != null
                    ? ` · confidence ${Math.round(cursorRecommendationConfidence * 100)}%`
                    : ""}
                  . Local Ollama answers text tasks; it does not edit the sandbox
                  unless you use Cursor SDK.
                </small>
                {cursorPathReasons.length > 0 && (
                  <ul className="muted-list">
                    {cursorPathReasons.slice(0, 3).map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            <RoutingTransparencyBlock
              routing={cursorRoutingRecommendation}
              title="Routing transparency (before the run)"
              caption="Selected and executed stages are filled in after the Cursor Agent run."
            />

            <div className="composer-submit">
              <button
                type="button"
                className="secondary"
                disabled={loading || !prompt.trim()}
                onClick={() => void refreshCursorRecommendation()}
              >
                Refresh recommendation
              </button>
              <button
                type="button"
                className="secondary"
                disabled={loading}
                onClick={() => void prepareCursorAgentMode()}
              >
                Recheck bridge
              </button>
            </div>
          </section>
        )}

        {reviewingClassification || continuingSession ? (
          <CodingSessionSetup
            codingSession={codingSession}
            selectedTaskType={selectedTaskType}
            workflow={workflow}
            context={codingContext}
            continuing={continuingSession}
            disabled={loading}
            onTaskTypeChange={(value) =>
              setSession((current) => ({
                ...current,
                selectedTaskType: value,
              }))
            }
            onWorkflowChange={(value) =>
              setSession((current) => ({ ...current, workflow: value }))
            }
            onContextChange={updateContext}
            onEditObjective={editObjective}
          />
        ) : null}

        <div className="composer-tools">
          <label
            className={
              loading || composerLocked || mode === "cursor_agent"
                ? "attachment-button disabled"
                : "attachment-button"
            }
            htmlFor="playground-attachment"
          >
            <span aria-hidden="true">+</span>
            Attach image
          </label>
          <input
            ref={fileInputRef}
            id="playground-attachment"
            className="attachment-input"
            type="file"
            accept="image/*"
            disabled={loading || composerLocked || mode === "cursor_agent"}
            onChange={(event) =>
              handleFileChange(event.target.files?.[0] ?? null)
            }
          />
          {attachment && (
            <span className="attachment-chip">
              <span className="attachment-name">{attachment.name}</span>
              <button
                type="button"
                disabled={loading}
                aria-label={`Remove ${attachment.name}`}
                onClick={removeAttachment}
              >
                Remove
              </button>
            </span>
          )}
          {mode === "cursor_agent" && (
            <small className="keyboard-hint">
              Image attach is unavailable in Cursor Agent Coding Run; describe
              the change in the objective instead.
            </small>
          )}
          <small id="playground-keyboard-hint" className="keyboard-hint">
            Enter to continue · Shift+Enter for a new line
          </small>
        </div>

        <div className="playground-policy">
          <span>Organization policy</span>
          <strong>{policyMode}</strong>
          <small>Managed by your organization owner or admin</small>
        </div>

        <div className="composer-submit">
          <span>
            {mode === "coding"
              ? "Raw code is not stored in the shared intelligence record."
              : mode === "cursor_agent"
                ? "Runs stay in the disposable sandbox. Your draft is preserved on failure."
                : "Your draft stays here if the request cannot be completed."}
          </span>
          <button
            className="primary"
            type="submit"
            disabled={loading || !hasDraft || submissionLocked}
          >
            {loading
              ? codingPhase === "draft" && mode === "coding"
                ? "Classifying..."
                : mode === "cursor_agent"
                  ? "Running Cursor Agent Coding Run…"
                  : "Working..."
              : primaryAction}
          </button>
        </div>
      </form>

      {loading && (
        <div className="request-progress" role="status">
          <span className="request-spinner" aria-hidden="true" />
          <div>
            <strong>
              {mode === "coding" && codingPhase === "draft"
                ? `${PRODUCT_NAME} is classifying the objective`
                : mode === "cursor_agent"
                  ? "Running Cursor Agent Coding Run…"
                  : `${PRODUCT_NAME} is working on your request`}
            </strong>
            <small>
              {mode === "coding" && codingPhase === "draft"
                ? "Preparing a correctable use-case classification before model execution."
                : mode === "cursor_agent"
                  ? "Waiting for the Cursor SDK bridge, applying workspace safety checks, then collecting the diff and validation."
                  : "Choosing a route, applying safety checks, and tracking cost."}
              {result && " Your previous answer remains available below."}
            </small>
          </div>
        </div>
      )}

      {error && (
        <div className="request-error" role="alert">
          <div>
            <strong>{PRODUCT_NAME} could not complete this step</strong>
            <p>{error}</p>
            <small>
              Your question and attachment were preserved.
              {result && " The previous successful result remains below."}
            </small>
          </div>
          <button
            className="retry-button"
            type="button"
            disabled={loading}
            onClick={() => void handleSubmit()}
          >
            Try again
          </button>
        </div>
      )}

      {mode === "cursor_agent" && cursorAgentResult && (
        <section className="result" aria-label="Cursor Agent Coding Run result">
          <div className="result-context">
            <span>Cursor Agent Coding Run</span>
            <p>{submittedPrompt}</p>
            <small>
              Selected: {cursorAgentResult.selected_model}
              {cursorAgentResult.recommended_model
                ? ` · Recommended: ${cursorAgentResult.recommended_model}`
                : ""}
              {cursorAgentResult.model_used
                ? ` · Used: ${cursorAgentResult.model_used}`
                : ""}
              {cursorAgentResult.sdk_run_id
                ? ` · Run: ${cursorAgentResult.sdk_run_id}`
                : ""}
              {cursorAgentResult.workspace_kind
                ? ` · Workspace: ${cursorAgentResult.workspace_kind}`
                : ""}
              {cursorAgentResult.validation_status
                ? ` · Validation: ${cursorAgentResult.validation_status}`
                : ""}
            </small>
          </div>
          <article className="answer-card">
            <header className="answer-header">
              <div className="answer-brandmark" aria-hidden="true">
                M
              </div>
              <div>
                <span>{PRODUCT_NAME} + Cursor SDK</span>
                <h2>Coding Run result</h2>
              </div>
              <span className="answer-state">
                {cursorAgentResult.status === "finished" &&
                cursorAgentResult.validation_status === "failed"
                  ? "finished · validation failed"
                  : cursorAgentResult.status === "finished" &&
                      cursorAgentResult.validation_status === "timed_out"
                    ? "finished · validation timed out"
                    : cursorAgentResult.status}
              </span>
            </header>
            <div className="answer-content">
              <ReactMarkdown>
                {cursorAgentResult.answer ||
                  cursorAgentResult.error ||
                  "*No answer content was returned.*"}
              </ReactMarkdown>
            </div>
            {cursorAgentResult.workspace_cwd && (
              <p className="muted">
                Workspace: <code>{cursorAgentResult.workspace_cwd}</code>
                {cursorAgentResult.sdk_sandbox_enabled != null
                  ? ` · SDK sandbox enabled: ${String(cursorAgentResult.sdk_sandbox_enabled)}`
                  : ""}
              </p>
            )}
            <div className="answer-content">
              <h3>Changed files</h3>
              {cursorAgentResult.changed_files.length > 0 ? (
                <ul className="muted-list">
                  {cursorAgentResult.changed_files.map((file) => (
                    <li key={file}>
                      <code>{file}</code>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">
                  No files changed in this run. The objective may already match
                  the sandbox, or the agent made no edits.
                </p>
              )}
            </div>
            <div className="answer-content">
              <h3>
                Diff for this run
                {cursorAgentResult.diff_truncated ? " (truncated)" : ""}
              </h3>
              {cursorAgentResult.diff_text ? (
                <>
                  <pre>
                    <code>{cursorAgentResult.diff_text}</code>
                  </pre>
                  <small>
                    Shown to you for this run only. Raw diffs are not persisted by
                    default
                    {cursorAgentResult.diff_fingerprint
                      ? ` · fingerprint ${cursorAgentResult.diff_fingerprint.slice(0, 12)}…`
                      : ""}
                    .
                  </small>
                </>
              ) : (
                <p className="muted">
                  No diff was returned for this run.
                  {cursorAgentResult.diff_fingerprint
                    ? ` A fingerprint is available (${cursorAgentResult.diff_fingerprint.slice(0, 12)}…).`
                    : ""}
                </p>
              )}
            </div>
            {cursorAgentResult.validation_command && (
              <div className="answer-content">
                <h3>
                  Validation
                  {cursorAgentResult.validation_status === "passed"
                    ? " — passed"
                    : cursorAgentResult.validation_status === "failed"
                      ? " — failed"
                      : cursorAgentResult.validation_status === "timed_out"
                        ? " — timed out"
                        : ""}
                </h3>
                <p>
                  <code>{cursorAgentResult.validation_command}</code> →{" "}
                  {cursorAgentResult.validation_status ?? "n/a"}
                  {cursorAgentResult.validation_exit_code != null
                    ? ` (exit ${cursorAgentResult.validation_exit_code})`
                    : ""}
                </p>
                {cursorAgentResult.validation_status === "failed" && (
                  <p className="muted">
                    The coding run finished, but validation did not pass. Review
                    the output below before treating this as a successful demo.
                  </p>
                )}
                {cursorAgentResult.validation_status === "timed_out" && (
                  <p className="muted">
                    Validation exceeded the time limit. Retry with a shorter
                    command, or reset the sandbox and try again.
                  </p>
                )}
                {(cursorAgentResult.validation_stdout ||
                  cursorAgentResult.validation_stderr) && (
                  <pre>
                    <code>
                      {[
                        cursorAgentResult.validation_stdout,
                        cursorAgentResult.validation_stderr,
                      ]
                        .filter(Boolean)
                        .join("\n")}
                    </code>
                  </pre>
                )}
              </div>
            )}
            <footer className="answer-footer">
              <span>{cursorAgentResult.claim}</span>
              <small>
                Fingerprint: {cursorAgentResult.result_fingerprint ?? "n/a"} ·
                Session: {cursorAgentResult.session_id ?? "n/a"} · Attempt:{" "}
                {cursorAgentResult.attempt_id ?? "n/a"}
              </small>
            </footer>
          </article>

          <RoutingTransparencyBlock
            routing={cursorAgentResult.routing}
            title="Routing transparency (this run)"
            caption="Recommended before the run, selected in the composer, executed by the Cursor SDK."
          />
        </section>
      )}

      {result && (
        <section
          ref={resultRef}
          className={resultIsPrevious ? "result previous" : "result"}
          tabIndex={-1}
          aria-labelledby="playground-answer-title"
        >
          {resultIsPrevious && (
            <div className="previous-result-note">
              This is the previous attempt. Your current coding-session prompt
              is shown above.
            </div>
          )}

          <div className="result-context">
            <span>{resultIsPrevious ? "Previous request" : "Your request"}</span>
            <p>
              {submittedPrompt ||
                (submittedAttachmentName
                  ? "Analyze the attached image"
                  : "Request")}
            </p>
            {submittedAttachmentName && (
              <small>Image: {submittedAttachmentName}</small>
            )}
          </div>

          <article className="answer-card">
            <header className="answer-header">
              <div className="answer-brandmark" aria-hidden="true">M</div>
              <div>
                <span>{PRODUCT_NAME} response</span>
                <h2 id="playground-answer-title">
                  {resultIsPrevious ? "Previous answer" : "Answer"}
                </h2>
              </div>
              <span
                className={
                  resultIsPrevious ? "answer-state previous" : "answer-state"
                }
              >
                {resultIsPrevious ? "Previous" : "Ready"}
              </span>
            </header>

            <div className="answer-content">
              <ReactMarkdown
                components={{
                  a: ({ node: _node, ...props }) => (
                    <a {...props} target="_blank" rel="noreferrer" />
                  ),
                  img: ({ node: _node, alt, src }) =>
                    src ? (
                      <a href={src} target="_blank" rel="noreferrer">
                        {alt || "Open referenced image"}
                      </a>
                    ) : null,
                }}
              >
                {result.answer || "*No answer content was returned.*"}
              </ReactMarkdown>
            </div>

            <footer className="answer-footer">
              <span>Delivered through your organization policy</span>
              <button type="button" onClick={focusOutcomeAction}>
                {canVerify
                  ? "Verify this outcome"
                  : evaluation
                    ? "View Model Fit"
                    : "Continue in composer"}
              </button>
            </footer>
          </article>

          <DecisionReceipt
            receipt={result.receipt}
            policyMode={policyMode}
          />

          {mode === "coding" &&
            result.coding_session?.tracking_status !== "recorded" && (
              <div className="tracking-warning" role="status">
                <strong>Outcome scoring is not available for this attempt.</strong>
                <span>
                  {trackingReason(result.coding_session?.reason)}
                  You can adjust the prompt and continue the same session.
                </span>
              </div>
            )}

          {canVerify && (
            <div ref={verificationRef}>
              <VerificationPanel
                key={tracking?.attempt_id}
                attemptNumber={tracking?.attempt_number ?? null}
                loading={verificationLoading}
                error={verificationError}
                onVerify={handleVerification}
              />
            </div>
          )}

          {evaluation && (
            <div ref={evaluationRef}>
              <ModelFitReceipt
                evaluation={evaluation}
                onStartNew={startNewCodingSession}
              />
            </div>
          )}
        </section>
      )}

      <div className="sr-only" role="status" aria-live="polite">
        {announcement}
      </div>
    </div>
  );
}

function CodingSessionSetup({
  codingSession,
  selectedTaskType,
  workflow,
  context,
  continuing,
  disabled,
  onTaskTypeChange,
  onWorkflowChange,
  onContextChange,
  onEditObjective,
}: {
  codingSession: PlaygroundSession["codingSession"];
  selectedTaskType: CodingTaskType;
  workflow: WorkflowType;
  context: CodingContext;
  continuing: boolean;
  disabled: boolean;
  onTaskTypeChange: (value: CodingTaskType) => void;
  onWorkflowChange: (value: WorkflowType) => void;
  onContextChange: (changes: Partial<CodingContext>) => void;
  onEditObjective: () => void;
}) {
  if (!codingSession) return null;
  return (
    <section className="coding-session-setup">
      <header>
        <div>
          <span className="receipt-eyebrow">
            {continuing ? "Active coding session" : "Classification review"}
          </span>
          <h2>
            {continuing
              ? "Keep the next attempt comparable"
              : "Confirm what kind of coding work this is"}
          </h2>
          <p>{codingSession.classification_reason}</p>
        </div>
        {!continuing && (
          <button type="button" disabled={disabled} onClick={onEditObjective}>
            Edit objective
          </button>
        )}
      </header>

      <div className="classification-confidence">
        <span>Predicted confidence</span>
        <strong>
          {Math.round(codingSession.classification_confidence * 100)}%
        </strong>
        {codingSession.clarification_required && (
          <small>Clarification recommended</small>
        )}
      </div>

      <div className="coding-setup-grid">
        <label>
          <span>Coding use case</span>
          <select
            value={selectedTaskType}
            disabled={disabled || continuing}
            onChange={(event) =>
              onTaskTypeChange(event.target.value as CodingTaskType)
            }
          >
            {TASK_TYPES.map((task) => (
              <option value={task.value} key={task.value}>{task.label}</option>
            ))}
          </select>
        </label>
        <label>
          <span>Workflow used</span>
          <select
            value={workflow}
            disabled={disabled}
            onChange={(event) =>
              onWorkflowChange(event.target.value as WorkflowType)
            }
          >
            {WORKFLOWS.map((option) => (
              <option value={option.value} key={option.value}>
                {option.label} · {option.detail}
              </option>
            ))}
          </select>
        </label>
      </div>

      <details className="context-signals">
        <summary>
          <span>
            <strong>Context characteristics</strong>
            <small>Characteristics only, not raw repository code</small>
          </span>
          <span>Configure</span>
        </summary>
        <div className="context-grid">
          <label>
            <span>Primary language</span>
            <input
              value={context.primary_language ?? ""}
              disabled={disabled}
              maxLength={80}
              placeholder="e.g. Python"
              onChange={(event) =>
                onContextChange({
                  primary_language: event.target.value || null,
                })
              }
            />
          </label>
          <label>
            <span>Repository size</span>
            <select
              value={context.repository_size}
              disabled={disabled}
              onChange={(event) =>
                onContextChange({
                  repository_size: event.target
                    .value as CodingContext["repository_size"],
                })
              }
            >
              <option value="unknown">Not specified</option>
              <option value="small">Small</option>
              <option value="medium">Medium</option>
              <option value="large">Large</option>
            </select>
          </label>
          <label>
            <span>Files supplied</span>
            <input
              type="number"
              min={0}
              max={10000}
              value={context.files_supplied}
              disabled={disabled}
              onChange={(event) =>
                onContextChange({
                  files_supplied: Math.max(0, Number(event.target.value) || 0),
                })
              }
            />
          </label>
          <label>
            <span>Test files supplied</span>
            <input
              type="number"
              min={0}
              max={10000}
              value={context.test_files_supplied}
              disabled={disabled}
              onChange={(event) =>
                onContextChange({
                  test_files_supplied: Math.max(
                    0,
                    Number(event.target.value) || 0,
                  ),
                })
              }
            />
          </label>
          <label>
            <span>Privacy classification</span>
            <select
              value={context.privacy_classification}
              disabled={disabled}
              onChange={(event) =>
                onContextChange({
                  privacy_classification: event.target
                    .value as CodingContext["privacy_classification"],
                })
              }
            >
              <option value="standard">Standard</option>
              <option value="sensitive">Sensitive</option>
              <option value="restricted">Restricted</option>
            </select>
          </label>
        </div>
        <div className="context-checks">
          <ContextCheckbox
            label="Error or stack trace supplied"
            checked={context.has_error_details}
            disabled={disabled}
            onChange={(checked) =>
              onContextChange({ has_error_details: checked })
            }
          />
          <ContextCheckbox
            label="Acceptance criteria supplied"
            checked={context.has_acceptance_criteria}
            disabled={disabled}
            onChange={(checked) =>
              onContextChange({ has_acceptance_criteria: checked })
            }
          />
          <ContextCheckbox
            label="Relevant tests supplied"
            checked={context.has_relevant_tests}
            disabled={disabled}
            onChange={(checked) =>
              onContextChange({ has_relevant_tests: checked })
            }
          />
        </div>
      </details>
    </section>
  );
}

function ContextCheckbox({
  label,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label>
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>{label}</span>
    </label>
  );
}

function trackingReason(reason: string | null | undefined): string {
  if (reason === "blocked_before_model_execution") {
    return "The guardrail stopped execution before a coding attempt existed. ";
  }
  return "The answer was delivered, but its attempt evidence could not be recorded. ";
}
