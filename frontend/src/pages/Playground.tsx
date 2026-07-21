import type { FormEvent, KeyboardEvent } from "react";
import type { PolicyMode } from "../types";
import type { PlaygroundSession } from "../playgroundSession";
import { runPrompt } from "../api";

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

          <details className="receipt-details" open>
            <summary>Decision Receipt</summary>

            <div
              className={
                result.usedMock ? "source-badge mock" : "source-badge live"
              }
            >
              Source: {result.usedMock ? "frontend mock fallback" : "n8n webhook"}
            </div>

            <div className="receipt">
              <Receipt label="guardrail_status" value={val(result.receipt?.guardrail_status)} />
              <Receipt
                label="output_guardrail_status"
                value={val(result.receipt?.output_guardrail_status)}
              />
              <Receipt label="cache_status" value={val(result.receipt?.cache_status)} />
              <Receipt
                label="cache_confidence"
                value={val(result.receipt?.cache_confidence)}
              />
              <Receipt label="cache_entry_id" value={val(result.receipt?.cache_entry_id)} />
              <Receipt label="selected_tier" value={val(result.receipt?.selected_tier)} />
              <Receipt label="provider" value={val(result.receipt?.provider)} />
              <Receipt label="model" value={val(result.receipt?.model)} />
              <Receipt label="executed_tier" value={val(result.receipt?.executed_tier)} />
              <Receipt
                label="actual_input_tokens"
                value={val(result.receipt?.actual_input_tokens)}
              />
              <Receipt
                label="actual_output_tokens"
                value={val(result.receipt?.actual_output_tokens)}
              />
              <Receipt
                label="actual_total_tokens"
                value={val(result.receipt?.actual_total_tokens)}
              />
              <Receipt label="actual_cost" value={money(result.receipt?.actual_cost)} />
              <Receipt
                label="actual_cost_saved"
                value={money(result.receipt?.actual_cost_saved)}
              />
              <Receipt label="latency_ms" value={val(result.receipt?.latency_ms)} />
              <Receipt label="used_fallback" value={val(result.receipt?.used_fallback)} />
              <Receipt
                label="actual_execution_attempt_count"
                value={val(result.receipt?.actual_execution_attempt_count)}
              />
              <Receipt
                label="prompt_redaction_applied"
                value={val(result.receipt?.prompt_redaction_applied)}
              />
              <Receipt
                label="privacy_enforced"
                value={val(result.receipt?.privacy_enforced)}
              />
              <Receipt
                label="cost_calculation_status"
                value={val(result.receipt?.cost_calculation_status)}
              />
              <Receipt
                label="estimated_tokens"
                value={val(result.receipt?.estimated_tokens)}
              />
              <Receipt
                label="estimated_cost"
                value={money(result.receipt?.estimated_cost)}
              />
              <Receipt label="cost_saved" value={money(result.receipt?.cost_saved)} />
              <Receipt label="savings_source" value={val(result.receipt?.savings_source)} />
              <Receipt label="savings_reason" value={val(result.receipt?.savings_reason)} />
              <Receipt label="reason" value={val(result.receipt?.reason)} />
              <Receipt
                label="detected_risk_type"
                value={val(result.receipt?.detected_risk_type)}
              />
              <Receipt
                label="output_guardrail_issues"
                value={list(result.receipt?.output_guardrail_issues)}
                wide
              />
              <Receipt label="has_image" value={val(result.receipt?.has_image)} />
              <Receipt label="image_class" value={val(result.receipt?.image_class)} />
              <Receipt
                label="image_filename"
                value={val(result.receipt?.image_filename)}
              />
              <Receipt
                label="image_confidence"
                value={val(result.receipt?.image_confidence)}
              />
              <Receipt
                label="visual_complexity"
                value={val(result.receipt?.visual_complexity)}
              />
              <Receipt
                label="needs_vision_model"
                value={val(result.receipt?.needs_vision_model)}
              />
              <Receipt label="graph_path" value={val(result.receipt?.graph_path)} />
              <Receipt label="branch_reason" value={val(result.receipt?.branch_reason)} wide />
              <Receipt label="task_type" value={val(result.receipt?.task_type)} />
              <Receipt
                label="complexity_level"
                value={val(result.receipt?.complexity_level)}
              />
              <Receipt
                label="complexity_score"
                value={val(result.receipt?.complexity_score)}
              />
              <Receipt
                label="compression_recommended"
                value={val(result.receipt?.compression_recommended)}
              />
              <Receipt
                label="compression_target_ratio"
                value={val(result.receipt?.compression_target_ratio)}
              />
              <Receipt
                label="compression_risk"
                value={val(result.receipt?.compression_risk)}
              />
              <Receipt label="fallback_tier" value={val(result.receipt?.fallback_tier)} />
              <Receipt
                label="estimated_baseline_cost"
                value={money(result.receipt?.estimated_baseline_cost)}
              />
              <Receipt
                label="estimated_optimized_cost"
                value={money(result.receipt?.estimated_optimized_cost)}
              />
              <Receipt
                label="compression_reason"
                value={val(result.receipt?.compression_reason)}
                wide
              />
              <Receipt
                label="optimization_reason"
                value={val(result.receipt?.optimization_reason)}
                wide
              />
            </div>

            {Array.isArray(result.receipt?.provider_attempts) &&
              result.receipt.provider_attempts.length > 0 && (
                <div className="receipt-reasons">
                  <span className="receipt-label">provider_attempts</span>
                  <ul>
                    {result.receipt.provider_attempts.map((a, i) => (
                      <li key={i}>{a}</li>
                    ))}
                  </ul>
                </div>
              )}

            {Array.isArray(result.receipt?.executed_nodes) &&
              result.receipt.executed_nodes.length > 0 && (
                <div className="receipt-reasons">
                  <span className="receipt-label">executed_nodes</span>
                  <ul>
                    {result.receipt.executed_nodes.map((n, i) => (
                      <li key={i}>{n}</li>
                    ))}
                  </ul>
                </div>
              )}

            {Array.isArray(result.receipt?.decision_reasons) &&
              result.receipt.decision_reasons.length > 0 && (
                <div className="receipt-reasons">
                  <span className="receipt-label">decision_reasons</span>
                  <ul>
                    {result.receipt.decision_reasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
          </details>
        </div>
      )}

      {attachment && (
        <p className="muted">Selected file: {attachment.name}</p>
      )}
    </div>
  );
}

function val(v: unknown): string {
  if (v === null || v === undefined || v === "") return "-";
  return String(v);
}

function money(v: unknown): string {
  if (typeof v !== "number" || Number.isNaN(v)) return "-";
  return `$${v}`;
}

function list(v: unknown): string {
  if (Array.isArray(v) && v.length > 0) return v.join(", ");
  return "-";
}

function Receipt({
  label,
  value,
  wide,
}: {
  label: string;
  value: string;
  wide?: boolean;
}) {
  return (
    <div className={wide ? "receipt-item wide" : "receipt-item"}>
      <span className="receipt-label">{label}</span>
      <span className="receipt-value">{value}</span>
    </div>
  );
}
