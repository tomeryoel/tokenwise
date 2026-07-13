import { useState } from "react";
import type { PolicyMode, RunResponse } from "../types";
import { runPrompt } from "../api";

interface Props {
  policyMode: PolicyMode;
  setPolicyMode: (m: PolicyMode) => void;
}

const MODES: PolicyMode[] = ["conservative", "balanced", "aggressive"];

export default function Playground({ policyMode, setPolicyMode }: Props) {
  const [prompt, setPrompt] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<RunResponse | null>(null);

  async function onRun() {
    if (!prompt.trim()) return;
    setLoading(true);
    setResult(null);
    const res = await runPrompt(prompt, policyMode);
    setResult(res);
    setLoading(false);
  }

  return (
    <div className="page">
      <h1>Playground</h1>

      <label className="field-label">Prompt</label>
      <textarea
        className="prompt"
        rows={6}
        placeholder="Ask something..."
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
      />

      <div className="row">
        {/* File upload is a placeholder in the skeleton (image analysis is Day 8). */}
        <label className="field-label">Attachment (placeholder)</label>
        <input type="file" disabled title="Coming later (image analyser)" />
      </div>

      <div className="row">
        <label className="field-label">Policy mode</label>
        <select
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

      <button className="primary" onClick={onRun} disabled={loading}>
        {loading ? "Running..." : "Run with TokenWise"}
      </button>

      {result && (
        <div className="result">
          <h2>Answer</h2>
          <div className="answer">{result.answer}</div>

          {/* Decision Receipt: title always visible; open by default. */}
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
              <Receipt
                label="optimization_reason"
                value={val(result.receipt?.optimization_reason)}
                wide
              />
            </div>
          </details>
        </div>
      )}
    </div>
  );
}

// Defensive formatters so a missing/odd field never crashes the receipt render.
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
