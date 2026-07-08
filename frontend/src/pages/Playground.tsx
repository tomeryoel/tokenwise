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
          {result.usedMock && (
            <div className="banner-warn">
              Temporary local mock (n8n webhook not reachable).
            </div>
          )}

          <h2>Answer</h2>
          <div className="answer">{result.answer}</div>

          <h2>Decision Receipt</h2>
          <div className="receipt">
            <Receipt label="Guardrail" value={result.receipt.guardrail_status} />
            <Receipt label="Cache" value={result.receipt.cache_status} />
            <Receipt label="Selected tier" value={result.receipt.selected_tier} />
            <Receipt
              label="Estimated tokens"
              value={String(result.receipt.estimated_tokens)}
            />
            <Receipt
              label="Estimated cost"
              value={`$${result.receipt.estimated_cost}`}
            />
            <Receipt label="Cost saved" value={`$${result.receipt.cost_saved}`} />
            <Receipt
              label="Reason"
              value={result.receipt.optimization_reason}
              wide
            />
          </div>
        </div>
      )}
    </div>
  );
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
