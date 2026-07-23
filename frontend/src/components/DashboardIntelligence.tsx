import type { DecisionIntelligenceSummary } from "../api";

function formatMoney(value: number): string {
  if (value === 0) return "$0";
  if (Math.abs(value) < 0.01) return `$${value.toFixed(6)}`;
  if (Math.abs(value) < 1) return `$${value.toFixed(4)}`;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

function formatRate(rate: number): string {
  return `${(rate * 100).toFixed(0)}%`;
}

function formatTaskType(taskType: string): string {
  return taskType
    .split("_")
    .map((word) => `${word.charAt(0).toUpperCase()}${word.slice(1)}`)
    .join(" ");
}

function metricStatusLabel(status: string): string {
  if (status === "qualified") return "Evidence-qualified";
  if (status === "provisional") return "Provisional evidence";
  return "Not enough evidence";
}

export default function DashboardIntelligence({
  summary,
  onStartCodingSession,
}: {
  summary: DecisionIntelligenceSummary;
  onStartCodingSession: () => void;
}) {
  const { coverage, model_fit: modelFit, cost_to_success: cost } = summary;
  const positiveOutcomes =
    summary.outcomes.succeeded + summary.outcomes.partially_succeeded;
  const strongConfidence =
    (coverage.confidence_counts.high ?? 0) +
    (coverage.confidence_counts.medium ?? 0);

  if (coverage.total_sessions === 0) {
    return (
      <section className="intelligence-empty" aria-labelledby="intelligence-empty-title">
        <div className="intelligence-empty-mark" aria-hidden="true">
          MF
        </div>
        <div>
          <span className="page-eyebrow">Coding decision intelligence</span>
          <h2 id="intelligence-empty-title">No verified coding sessions yet</h2>
          <p>
            Run a Coding session, record its outcome, and MomiHelm will begin
            measuring Model Fit, Cost-to-Success, and route suitability here.
          </p>
        </div>
        <button
          className="primary intelligence-start-action"
          type="button"
          onClick={onStartCodingSession}
        >
          Start a verified session
        </button>
      </section>
    );
  }

  return (
    <section
      className="decision-intelligence"
      aria-labelledby="decision-intelligence-title"
    >
      <header className="intelligence-heading">
        <div>
          <span className="page-eyebrow">Coding decision intelligence</span>
          <h2 id="decision-intelligence-title">
            Was the right AI used in the right way?
          </h2>
          <p>
            Outcome-based evidence across {coverage.total_sessions} coding{" "}
            {coverage.total_sessions === 1 ? "session" : "sessions"} created in
            this reporting period.
          </p>
        </div>
        <span className={`intelligence-status ${modelFit.status}`}>
          {metricStatusLabel(modelFit.status)}
        </span>
      </header>

      <div className="intelligence-hero">
        <div className="model-fit-spotlight">
          <div className="model-fit-label">
            <span>Average Model Fit</span>
            <small>{metricStatusLabel(modelFit.status)}</small>
          </div>
          <div className="model-fit-value">
            <strong>
              {modelFit.value == null ? "Unavailable" : modelFit.value.toFixed(1)}
            </strong>
            {modelFit.value != null && <span>/ 100</span>}
          </div>
          <p>{modelFit.reason}</p>
          <div className="model-fit-sample">
            <strong>{modelFit.sample_size}</strong>
            <span>
              scored of {modelFit.eligible_sessions} completed sessions
            </span>
          </div>
        </div>

        <div className="intelligence-kpi-grid">
          <IntelligenceKpi
            label="Average Cost-to-Success"
            value={cost.value == null ? "Unavailable" : formatMoney(cost.value)}
            detail={
              cost.value == null
                ? "Missing complete execution cost"
                : `${cost.sample_size} of ${cost.eligible_sessions} successful sessions`
            }
            tone={cost.value == null ? "muted" : "positive"}
          />
          <IntelligenceKpi
            label="Overpowered sessions"
            value={String(summary.power.overpowered)}
            detail="Comparable fit available at lower cost"
            tone={summary.power.overpowered ? "warning" : "neutral"}
          />
          <IntelligenceKpi
            label="Underpowered sessions"
            value={String(summary.power.underpowered)}
            detail="A stronger route was supported by evidence"
            tone={summary.power.underpowered ? "danger" : "neutral"}
          />
          <IntelligenceKpi
            label="Positive outcomes"
            value={String(positiveOutcomes)}
            detail={`${summary.outcomes.succeeded} succeeded · ${summary.outcomes.partially_succeeded} partial`}
            tone="info"
          />
        </div>
      </div>

      <div className="intelligence-coverage" aria-label="Evidence coverage">
        <CoverageFact
          label="Automated evidence"
          value={formatRate(coverage.evidence_coverage_rate)}
          detail={`${coverage.automated_evidence_sessions} of ${coverage.terminal_sessions} completed sessions`}
        />
        <CoverageFact
          label="Latest evaluations"
          value={`${coverage.evaluated_sessions}/${coverage.total_sessions}`}
          detail="One latest evaluation per session"
        />
        <CoverageFact
          label="Final Model Fit"
          value={String(coverage.final_sessions)}
          detail={`${coverage.provisional_sessions} provisional`}
        />
        <CoverageFact
          label="Strong confidence"
          value={String(strongConfidence)}
          detail="Medium or high evidence confidence"
        />
        <CoverageFact
          label="Route classification"
          value={formatRate(summary.power.coverage_rate)}
          detail={`${summary.power.classified_sessions} evidence-classified sessions`}
        />
      </div>

      <div className="intelligence-detail-grid">
        <section className="recommendation-card">
          <div className="recommendation-card-heading">
            <div>
              <span>Top recommendation</span>
              <h3>{summary.top_recommendation?.title ?? "Collect more evidence"}</h3>
            </div>
            {summary.top_recommendation && (
              <span
                className={`recommendation-evidence ${summary.top_recommendation.evidence_status}`}
              >
                {summary.top_recommendation.evidence_status}
              </span>
            )}
          </div>
          <p>
            {summary.top_recommendation?.detail ??
              "Complete a verified coding session to unlock an actionable recommendation."}
          </p>
          <div className="recommendation-action">
            <span>Recommended action</span>
            <strong>
              {summary.top_recommendation?.action ??
                "Run a coding session and record its outcome."}
            </strong>
          </div>
          {summary.top_recommendation && (
            <small>
              Based on {summary.top_recommendation.affected_sessions} affected{" "}
              {summary.top_recommendation.affected_sessions === 1
                ? "session"
                : "sessions"}
              .
            </small>
          )}
        </section>

        <section className="task-intelligence-card">
          <div className="task-intelligence-heading">
            <div>
              <span>Use-case performance</span>
              <h3>Model Fit by coding task</h3>
            </div>
            <small>
              {summary.average_attempts_per_session.toFixed(1)} attempts per session
            </small>
          </div>
          <div className="task-intelligence-list">
            {summary.task_types.slice(0, 6).map((task) => (
              <div className="task-intelligence-row" key={task.task_type}>
                <div>
                  <strong>{formatTaskType(task.task_type)}</strong>
                  <span>
                    {task.sessions} {task.sessions === 1 ? "session" : "sessions"}{" "}
                    · {task.average_attempts.toFixed(1)} attempts
                  </span>
                </div>
                <div className="task-fit-value">
                  <strong>
                    {task.average_model_fit == null
                      ? "Not scored"
                      : task.average_model_fit.toFixed(1)}
                  </strong>
                  <span>
                    {task.scored_sessions}/{task.sessions} scored
                  </span>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}

function IntelligenceKpi({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail: string;
  tone: "positive" | "warning" | "danger" | "neutral" | "muted" | "info";
}) {
  return (
    <div className={`intelligence-kpi ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function CoverageFact({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="coverage-fact">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}
