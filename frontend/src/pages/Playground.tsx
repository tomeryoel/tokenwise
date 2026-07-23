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
  recordVerification,
  runPrompt,
  updateCodingSession,
} from "../api";
import { PRODUCT_NAME } from "../brand";
import DecisionReceipt from "../components/DecisionReceipt";
import ModelFitReceipt from "../components/ModelFitReceipt";
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

    if (mode === "coding" && codingPhase === "draft") {
      await classifyObjective();
      return;
    }
    await executeRequest();
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
        : "Quick-question mode is ready.",
    );
  }

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

  const primaryAction =
    mode === "quick"
      ? `Ask ${PRODUCT_NAME}`
      : codingPhase === "draft"
        ? "Review coding objective"
        : codingPhase === "review"
          ? "Run coding attempt"
          : codingPhase === "awaiting_verification"
            ? "Verify current attempt below"
            : codingPhase === "evaluated"
              ? "Session evaluated"
              : "Run next attempt";

  return (
    <div className="page playground-page">
      <header className="playground-header">
        <div>
          <span className="page-eyebrow">AI coding decision intelligence</span>
          <h1>Playground</h1>
          <p>
            Run a verified coding session to measure Model Fit and
            Cost-to-Success, or use Quick question for the original lightweight
            experience.
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
          onKeyDown={handlePromptKeyDown}
        />

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
              loading || composerLocked
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
            disabled={loading || composerLocked}
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
                : `${PRODUCT_NAME} is working on your request`}
            </strong>
            <small>
              {mode === "coding" && codingPhase === "draft"
                ? "Preparing a correctable use-case classification before model execution."
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
