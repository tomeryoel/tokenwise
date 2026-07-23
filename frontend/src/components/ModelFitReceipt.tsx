import type { DecisionEvaluation } from "../types";

interface Props {
  evaluation: DecisionEvaluation;
  onStartNew: () => void;
}

export default function ModelFitReceipt({
  evaluation,
  onStartNew,
}: Props) {
  const { model_fit: fit, cost_to_success: cost } = evaluation;
  const score = fit.value == null ? "—" : Math.round(fit.value).toString();
  const statusLabel =
    fit.status === "unavailable"
      ? "More evidence needed"
      : fit.status === "provisional"
        ? "Provisional fit"
        : "Verified fit";

  return (
    <section className="model-fit-receipt" aria-labelledby="model-fit-title">
      <header className="model-fit-hero">
        <div className={`model-fit-score ${fit.status}`}>
          <strong>{score}</strong>
          <span>{fit.value == null ? "No score" : "out of 100"}</span>
        </div>
        <div>
          <span className="receipt-eyebrow">Coding outcome intelligence</span>
          <h3 id="model-fit-title">Model Fit</h3>
          <p>{fit.reason}</p>
        </div>
        <div className="fit-status-stack">
          <span className={`fit-status ${fit.status}`}>{statusLabel}</span>
          <small>{humanize(fit.confidence)} confidence</small>
        </div>
      </header>

      <div className="fit-highlights">
        <FitHighlight
          label="Cost-to-Success"
          value={
            cost.cost_to_success == null
              ? "Unavailable"
              : formatMoney(cost.cost_to_success)
          }
          detail={
            cost.cost_to_success == null
              ? `Known spend ${formatMoney(cost.cost_spent)}`
              : `${humanize(cost.cost_basis)} cost basis`
          }
        />
        <FitHighlight
          label="Attempts"
          value={
            cost.attempts_to_success == null
              ? "Not verified"
              : String(cost.attempts_to_success)
          }
          detail={
            cost.time_to_success_ms == null
              ? "Time-to-success unavailable"
              : formatDuration(cost.time_to_success_ms)
          }
        />
        {evaluation.fit_gap.value != null && (
          <FitHighlight
            label="Fit Gap"
            value={`${evaluation.fit_gap.value.toFixed(1)} points`}
            detail={evaluation.fit_gap.reason}
          />
        )}
        {evaluation.power_classification.status !== "unavailable" && (
          <FitHighlight
            label="Route assessment"
            value={humanize(evaluation.power_classification.status)}
            detail={evaluation.power_classification.reason}
          />
        )}
      </div>

      <details className="fit-details">
        <summary>
          <span>
            <strong>How this score was calculated</strong>
            <small>
              {evaluation.scoring_version} · {fit.evidence.length} evidence
              signal{fit.evidence.length === 1 ? "" : "s"}
            </small>
          </span>
          <span>View components</span>
        </summary>
        <div className="fit-component-grid">
          {Object.entries(fit.components).map(([name, value]) => (
            <div key={name}>
              <span>{humanize(name)}</span>
              <strong>
                {value == null ? "Missing" : `${Math.round(value * 100)}%`}
              </strong>
            </div>
          ))}
        </div>
        {fit.missing_components.length > 0 && (
          <p className="fit-missing">
            Missing for a final score:{" "}
            {fit.missing_components.map(humanize).join(", ")}.
          </p>
        )}
        {evaluation.fit_gap.value == null && (
          <p className="fit-missing">
            Fit Gap unavailable: {evaluation.fit_gap.reason}
          </p>
        )}
        {evaluation.power_classification.status === "unavailable" && (
          <p className="fit-missing">
            Route assessment unavailable:{" "}
            {evaluation.power_classification.reason}
          </p>
        )}
        <p className="fit-cost-note">{cost.reason}</p>
      </details>

      <footer className="fit-footer">
        <span>
          MomiHelm communicates uncertainty instead of inventing benchmark
          evidence.
        </span>
        <button type="button" onClick={onStartNew}>
          Start a new coding session
        </button>
      </footer>
    </section>
  );
}

function FitHighlight({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="fit-highlight">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function humanize(value: string): string {
  if (!value) return "Unavailable";
  const text = value.replace(/[_-]+/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function formatMoney(value: number): string {
  if (value === 0) return "$0.00";
  const digits = Math.abs(value) < 0.001 ? 6 : 4;
  return `$${value.toFixed(digits)}`;
}

function formatDuration(milliseconds: number): string {
  if (milliseconds < 1000) return `${milliseconds} ms`;
  const seconds = milliseconds / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)} seconds`;
  return `${(seconds / 60).toFixed(1)} minutes`;
}
