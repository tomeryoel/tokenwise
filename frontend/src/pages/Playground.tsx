import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import ReactMarkdown from "react-markdown";
import { runPrompt } from "../api";
import { PRODUCT_NAME } from "../brand";
import DecisionReceipt from "../components/DecisionReceipt";
import type { PlaygroundSession } from "../playgroundSession";
import type { PolicyMode } from "../types";

interface Props {
  policyMode: PolicyMode;
  session: PlaygroundSession;
  setSession: React.Dispatch<React.SetStateAction<PlaygroundSession>>;
}

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
  } = session;
  const promptRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const resultRef = useRef<HTMLElement>(null);
  const previousResultRef = useRef(result);
  const [announcement, setAnnouncement] = useState("");
  const hasDraft = Boolean(prompt.trim() || attachment);
  const resultIsPrevious = Boolean(result && (loading || error || hasDraft));

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

  async function handleSubmit(e?: FormEvent) {
    e?.preventDefault();
    if (loading) return;
    if (!prompt.trim() && !attachment) return;

    const requestPrompt = prompt.trim();
    const requestAttachment = attachment;
    setSession((s) => ({ ...s, loading: true, error: null }));
    setAnnouncement(`${PRODUCT_NAME} is working on your request.`);

    try {
      const res = await runPrompt(requestPrompt, requestAttachment);
      setSession((s) => ({
        ...s,
        prompt: "",
        loading: false,
        result: res,
        error: null,
        attachment: null,
        submittedPrompt: requestPrompt,
        submittedAttachmentName: requestAttachment?.name ?? null,
      }));
      if (fileInputRef.current) fileInputRef.current.value = "";
      setAnnouncement(`${PRODUCT_NAME}'s answer is ready.`);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Request failed";
      setSession((s) => ({
        ...s,
        loading: false,
        error: message,
      }));
      setAnnouncement(
        `${PRODUCT_NAME} could not complete the request. Your draft was preserved.`,
      );
    }
  }

  function handlePromptKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Enter" || e.shiftKey) return;
    if (e.nativeEvent.isComposing) return;
    e.preventDefault();
    void handleSubmit();
  }

  function handleFileChange(file: File | null) {
    setSession((s) => ({ ...s, attachment: file, error: null }));
  }

  function removeAttachment() {
    if (fileInputRef.current) fileInputRef.current.value = "";
    setSession((s) => ({ ...s, attachment: null, error: null }));
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

  return (
    <div className="page playground-page">
      <header className="playground-header">
        <div>
          <span className="page-eyebrow">Optimized AI workspace</span>
          <h1>Playground</h1>
          <p>
            Ask naturally. {PRODUCT_NAME} will choose the safest,
            most cost-effective route allowed by your organization.
          </p>
        </div>
      </header>

      <form
        className="playground-composer"
        onSubmit={handleSubmit}
        aria-busy={loading}
      >
        <label className="field-label" htmlFor="playground-prompt">
          What would you like help with?
        </label>
        <textarea
          ref={promptRef}
          id="playground-prompt"
          className="prompt"
          rows={6}
          placeholder="Ask a question, analyze an idea, or request code..."
          value={prompt}
          disabled={loading}
          aria-describedby="playground-keyboard-hint"
          onChange={(e) =>
            setSession((s) => ({
              ...s,
              prompt: e.target.value,
              error: null,
            }))
          }
          onKeyDown={handlePromptKeyDown}
        />

        <div className="composer-tools">
          <label
            className={
              loading ? "attachment-button disabled" : "attachment-button"
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
            disabled={loading}
            onChange={(e) => handleFileChange(e.target.files?.[0] ?? null)}
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
            Enter to send · Shift+Enter for a new line
          </small>
        </div>

        <div className="playground-policy">
          <span>Organization policy</span>
          <strong>{policyMode}</strong>
          <small>Managed by your organization owner or admin</small>
        </div>

        <div className="composer-submit">
          <span>Your draft stays here if the request cannot be completed.</span>
          <button
            className="primary"
            type="submit"
            disabled={loading || !hasDraft}
          >
            {loading ? "Working..." : `Ask ${PRODUCT_NAME}`}
          </button>
        </div>
      </form>

      {loading && (
        <div className="request-progress" role="status">
          <span className="request-spinner" aria-hidden="true" />
          <div>
            <strong>{PRODUCT_NAME} is working on your request</strong>
            <small>
              Choosing a route, applying safety checks, and tracking cost.
              {result && " Your previous answer remains available below."}
            </small>
          </div>
        </div>
      )}

      {error && (
        <div className="request-error" role="alert">
          <div>
            <strong>{PRODUCT_NAME} could not complete this request</strong>
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
              This is your previous completed answer. Your current draft or
              request is shown above.
            </div>
          )}

          <div className="result-context">
            <span>
              {resultIsPrevious ? "Previous request" : "Your request"}
            </span>
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
              <div className="answer-brandmark" aria-hidden="true">
                M
              </div>
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
              <button type="button" onClick={focusComposer}>
                Ask another question
              </button>
            </footer>
          </article>

          <DecisionReceipt
            receipt={result.receipt}
            policyMode={policyMode}
          />
        </section>
      )}

      <div className="sr-only" role="status" aria-live="polite">
        {announcement}
      </div>
    </div>
  );
}
