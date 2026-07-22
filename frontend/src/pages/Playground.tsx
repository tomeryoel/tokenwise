import type { FormEvent, KeyboardEvent } from "react";
import type { PolicyMode } from "../types";
import type { PlaygroundSession } from "../playgroundSession";
import { runPrompt } from "../api";
import DecisionReceipt from "../components/DecisionReceipt";

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
      if (res.usedMock) {
        setSession((s) => ({
          ...s,
          loading: false,
          error: "n8n webhook unavailable — showing frontend mock fallback",
          result: s.result ?? res,
        }));
      } else {
        setSession((s) => ({
          ...s,
          loading: false,
          error: null,
          result: res,
        }));
      }
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
          {loading ? "Running..." : "Run with TokenWise"}
        </button>
      </form>

      {loading && (
        <div className="banner-info">Running request through TokenWise…</div>
      )}

      {error && <div className="banner-info">{error}</div>}

      {result && (
        <div className="result">
          <h2>Answer</h2>
          <div className="answer">{result.answer}</div>

          <DecisionReceipt
            receipt={result.receipt}
            policyMode={policyMode}
            usedMock={result.usedMock}
          />
        </div>
      )}

      {attachment && (
        <p className="muted">Selected file: {attachment.name}</p>
      )}
    </div>
  );
}
