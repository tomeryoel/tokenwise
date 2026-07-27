import type { RoutingDecisionReceipt } from "../types";
import {
  buildRoutingView,
  NOT_RECORDED,
  type RoutingStageView,
} from "../routingTransparency";

interface Props {
  routing: RoutingDecisionReceipt | null | undefined;
  /** Shown when a run has not produced selected/executed facts yet. */
  title?: string;
  caption?: string;
}

/**
 * Shared routing transparency block: recommended -> selected -> executed, with
 * the basis, reason codes, assumptions, alternatives, and cost rationale that
 * the backend reported. Responses without a routing receipt render nothing so
 * older answers keep working.
 */
export default function RoutingTransparencyBlock({
  routing,
  title = "Routing transparency",
  caption,
}: Props) {
  const view = buildRoutingView(routing);
  if (!view) return null;

  return (
    <section className="routing-transparency" aria-label={title}>
      <div className="routing-header">
        <div>
          <strong>{title}</strong>
          <small>
            {caption ??
              "How MomiHelm recommended, selected, and executed this request."}
          </small>
        </div>
        <span className="routing-basis">
          Basis: {view.basis} · Confidence {view.confidence}
        </span>
      </div>

      {view.warnings.length > 0 && (
        <ul className="routing-warnings">
          {view.warnings.map((warning) => (
            <li key={warning.text} className={`routing-warning ${warning.tone}`}>
              {warning.text}
            </li>
          ))}
        </ul>
      )}

      <div className="routing-stages">
        {view.stages.map((stage) => (
          <RoutingStage key={stage.name} stage={stage} />
        ))}
      </div>

      <p className="routing-cost">{view.costHeadline}</p>

      <details className="receipt-section">
        <summary>
          <span>
            <strong>Why this route</strong>
            <small>{view.basisDetail || "Reason codes and assumptions"}</small>
          </span>
          <span className="section-action">View details</span>
        </summary>
        <div className="routing-details">
          <RoutingList label="Reason codes" items={view.reasons} />
          <RoutingList label="Assumptions" items={view.assumptions} />
          <div className="routing-detail-group">
            <h4>Alternatives</h4>
            {view.alternatives.length === 0 ? (
              <p className="muted">{NOT_RECORDED}</p>
            ) : (
              <ul className="muted-list">
                {view.alternatives.map((alternative) => (
                  <li key={`${alternative.kind}-${alternative.target}`}>
                    <strong>{alternative.label}:</strong> {alternative.target}
                    {alternative.reasons.length > 0
                      ? ` — ${alternative.reasons.join(" ")}`
                      : ""}
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="routing-detail-group">
            <h4>Cost comparison</h4>
            <div className="receipt-facts">
              {view.costRows.map((row) => (
                <div className="receipt-fact" key={row.label}>
                  <span>{row.label}</span>
                  <strong>{row.value}</strong>
                </div>
              ))}
            </div>
          </div>
          <div className="routing-detail-group">
            <h4>Fingerprints</h4>
            <div className="receipt-facts">
              {view.fingerprints.map((row) => (
                <div className="receipt-fact" key={row.label}>
                  <span>{row.label}</span>
                  <strong>{row.value}</strong>
                </div>
              ))}
            </div>
            <small className="muted">
              Structured metadata only. Prompts, answers, and diffs are never
              stored in this receipt.
            </small>
          </div>
        </div>
      </details>
    </section>
  );
}

function RoutingStage({ stage }: { stage: RoutingStageView }) {
  return (
    <div className={stage.recorded ? "routing-stage" : "routing-stage unrecorded"}>
      <span className="routing-stage-name">{stage.name}</span>
      <strong>{stage.path}</strong>
      <span className="routing-stage-detail">Model: {stage.model}</span>
      <span className="routing-stage-detail">{stage.detail}</span>
    </div>
  );
}

function RoutingList({ label, items }: { label: string; items: string[] }) {
  return (
    <div className="routing-detail-group">
      <h4>{label}</h4>
      {items.length === 0 ? (
        <p className="muted">{NOT_RECORDED}</p>
      ) : (
        <ul className="muted-list">
          {items.map((item, index) => (
            <li key={`${label}-${index}`}>{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
