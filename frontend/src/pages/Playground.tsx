import type { FormEvent, KeyboardEvent } from "react";
import type { PolicyMode } from "../types";
import type { PlaygroundSession } from "../playgroundSession";
import { runPrompt } from "../api";
import DecisionReceipt from "../components/DecisionReceipt";
import { PRODUCT_NAME } from "../brand";

interface Props {
  policyMode: PolicyMode;
  setPolicyMode: (m: PolicyMode) => void;
  session: PlaygroundSession;
  setSession: React.Dispatch<React.SetStateAction<PlaygroundSession>>;
}

const MODES: PolicyMode[] = ["conservative", "balanced", "aggressive"];

export default function Playground({
  policyMode,
  setPolicyMode,
  session,
  setSession,
}: Props) {
  const { prompt, loading, result, error, attachment } = session;

  async function handleSubmit(e?: FormEvent) {
    e?.preventDefault();
    if (loading) return;
    if (!prompt.trim() && !attachment) return;

    setSession((s) => ({ ...s, loading: true, error: null }));

    try {
      const res = await runPrompt(prompt, policyMode, attachment);
      setSession((s) => ({
        ...s,
        loading: false,
        error: null,
        result: res,
      }));
    } catch (err) {
      const message = err instanceof Error ? err.message : "Request failed";
      setSession((s) => ({
        ...s,
        loading: false,
        error: message,
      }));
    }
  }

  function handlePromptKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Enter" || e.shiftKey) return;
    if (e.nativeEvent.isComposing) return;
    e.preventDefault();
    void handleSubmit();
  }

  function handleFileChange(file: File | null) {
    setSession((s) => ({ ...s, attachment: file }));
  }

  return (
    <div className="page">
      <h1>Playground</h1>

      <form onSubmit={handleSubmit}>
        <label className="field-label" htmlFor="playground-prompt">
          Prompt
        </label>
        <textarea
          id="playground-prompt"
          className="prompt"
          rows={6}
          placeholder="Ask something..."
          value={prompt}
          onChange={(e) =>
            setSession((s) => ({ ...s, prompt: e.target.value }))
          }
          onKeyDown={handlePromptKeyDown}
        />

        <div className="row">
          <label className="field-label" htmlFor="playground-attachment">
            Image attachment
          </label>
          <input
            id="playground-attachment"
            type="file"
            accept="image/*"
            onChange={(e) => handleFileChange(e.target.files?.[0] ?? null)}
          />
        </div>

        <div className="row">
          <label className="field-label" htmlFor="playground-policy">
            Policy mode
          </label>
          <select
            id="playground-policy"
            value={policyMode}
            onChange={(e) => setPolicyMode(e.target.value as PolicyMode)}
          >
            {MODES.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>

        <button className="primary" type="submit" disabled={loading}>
          {loading ? "Running..." : `Run with ${PRODUCT_NAME}`}
        </button>
      </form>

      {loading && (
        <div className="banner-info">
          Running request through {PRODUCT_NAME}...
        </div>
      )}

      {error && (
        <div className="request-error" role="alert">
          <div>
            <strong>{PRODUCT_NAME} could not complete this request</strong>
            <p>{error}</p>
            <small>
              No mock answer was generated.
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
        <div className="result">
          <h2>{error ? "Previous successful answer" : "Answer"}</h2>
          <div className="answer">{result.answer}</div>

          <DecisionReceipt
            receipt={result.receipt}
            policyMode={policyMode}
          />
        </div>
      )}

      {attachment && (
        <p className="muted">Selected file: {attachment.name}</p>
      )}
    </div>
  );
}
