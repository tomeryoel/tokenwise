import { useEffect, useState, type FormEvent } from "react";
import { fetchUsageSummary, type UsageSummary } from "../api";
import { PRODUCT_NAME } from "../brand";
import type { AuthUser } from "../types";

const PERIOD_OPTIONS = [7, 30, 90];

const SOURCE_LABELS: Record<string, string> = {
  guardrails_cost_governance: "Guardrail governance",
  semantic_cache: "Semantic cache",
  model_routing: "Model routing",
  prompt_compression: "Prompt compression",
  image_analysis: "Image analysis",
  unknown: "Other",
};

function formatRate(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

function formatPercentage(value: number): string {
  return `${value.toFixed(1)}%`;
}

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

function formatLatency(value: number): string {
  if (value >= 1000) return `${(value / 1000).toFixed(2)} sec`;
  return `${Math.round(value)} ms`;
}

function formatInteger(value: number): string {
  return Math.round(value).toLocaleString("en-US");
}

function formatRequestCount(value: number): string {
  const count = Math.round(value);
  return `${formatInteger(count)} ${count === 1 ? "request" : "requests"}`;
}

function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source.replace(/_/g, " ");
}

export default function Dashboard({ user }: { user: AuthUser }) {
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [periodDays, setPeriodDays] = useState(30);
  const [departmentInput, setDepartmentInput] = useState("");
  const [appliedDepartment, setAppliedDepartment] = useState("");
  const [operatingCostInput, setOperatingCostInput] = useState("");
  const [appliedOperatingCost, setAppliedOperatingCost] = useState<number>();
  const [roiInputError, setRoiInputError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchUsageSummary(
      user.can_manage ? appliedDepartment || undefined : undefined,
      periodDays,
      appliedOperatingCost,
    )
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    appliedDepartment,
    appliedOperatingCost,
    periodDays,
    refreshKey,
    user.can_manage,
  ]);

  function applyDepartmentFilter(event: FormEvent) {
    event.preventDefault();
    setAppliedDepartment(departmentInput.trim());
  }

  function clearDepartmentFilter() {
    setDepartmentInput("");
    setAppliedDepartment("");
  }

  function calculateRoi(event: FormEvent) {
    event.preventDefault();
    const operatingCost = Number(operatingCostInput);
    if (!operatingCostInput.trim() || !Number.isFinite(operatingCost) || operatingCost <= 0) {
      setRoiInputError("Enter an operating cost greater than zero.");
      return;
    }
    setRoiInputError(null);
    setAppliedOperatingCost(operatingCost);
  }

  function clearRoiScenario() {
    setOperatingCostInput("");
    setAppliedOperatingCost(undefined);
    setRoiInputError(null);
  }

  const savingsSources = summary
    ? Object.entries(summary.savings_by_source)
        .map(([source, savings]) => ({
          source,
          savings,
          requests: summary.requests_by_source[source] ?? 0,
        }))
        .filter((row) => row.savings > 0 || row.requests > 0)
        .sort((a, b) => b.savings - a.savings)
    : [];

  const policyRows = summary
    ? ["conservative", "balanced", "aggressive"].map((mode) => ({
        mode,
        requests: summary.requests_by_policy_mode[mode] ?? 0,
        savings: summary.savings_by_policy_mode[mode] ?? 0,
      }))
    : [];

  const maxSourceSavings = Math.max(0, ...savingsSources.map((row) => row.savings));
  const maxPolicyRequests = Math.max(0, ...policyRows.map((row) => row.requests));

  return (
    <div className="page dashboard-page">
      <header className="dashboard-header">
        <div>
          <span className="page-eyebrow">Live usage intelligence</span>
          <h1>Dashboard</h1>
          <p>
            {user.can_manage
              ? `Organization-scoped ${PRODUCT_NAME} usage, cost avoidance, and operating behavior.`
              : `Your ${PRODUCT_NAME} usage, cost avoidance, and operating behavior.`}
          </p>
        </div>
        <div className={`dashboard-live-status ${error ? "stale" : ""}`}>
          <span aria-hidden="true" />
          {error
            ? summary
              ? "Previous SQLite data"
              : "Analytics unavailable"
            : loading && summary
              ? "Refreshing live data"
              : "Live SQLite data"}
        </div>
      </header>

      <form className="dashboard-filter-bar" onSubmit={applyDepartmentFilter}>
        <label className="dashboard-filter-field compact">
          <span>Reporting period</span>
          <select
            value={periodDays}
            onChange={(event) => setPeriodDays(Number(event.target.value))}
          >
            {PERIOD_OPTIONS.map((days) => (
              <option value={days} key={days}>
                Last {days} days
              </option>
            ))}
          </select>
        </label>
        {user.can_manage ? (
          <>
            <label className="dashboard-filter-field">
              <span>Department filter</span>
              <input
                value={departmentInput}
                onChange={(event) => setDepartmentInput(event.target.value)}
                placeholder="All departments"
              />
            </label>
            <div className="dashboard-filter-actions">
              <button className="secondary-button" type="submit">
                Apply
              </button>
              {appliedDepartment && (
                <button
                  className="text-button"
                  type="button"
                  onClick={clearDepartmentFilter}
                >
                  Clear
                </button>
              )}
            </div>
          </>
        ) : (
          <div className="dashboard-scope">
            <span>Data scope</span>
            <strong>Your account only</strong>
          </div>
        )}
      </form>

      {error && (
        <div className="analytics-error" role="alert">
          <div>
            <strong>Live analytics could not be refreshed</strong>
            <p>{error}</p>
            {summary && <small>The previous successful summary remains visible.</small>}
          </div>
          <button
            className="retry-button"
            type="button"
            onClick={() => setRefreshKey((key) => key + 1)}
          >
            Try again
          </button>
        </div>
      )}

      {loading && !summary && (
        <div className="dashboard-loading" role="status">
          <span />
          Reading usage outcomes from SQLite…
        </div>
      )}

      {!loading && !error && summary?.total_requests === 0 && (
        <div className="dashboard-empty">
          <span>Waiting for usage data</span>
          <h2>No requests match this view yet</h2>
          <p>
            Run a request through Playground or clear the department filter to
            populate this reporting period.
          </p>
        </div>
      )}

      {summary && summary.total_requests > 0 && (
        <>
          <section className="analytics-hero" aria-labelledby="analytics-outcome-title">
            <div className="analytics-outcome">
              <span id="analytics-outcome-title">Modeled cost avoided</span>
              <strong>
                {formatMoney(summary.total_modeled_cost_avoidance)}
              </strong>
              <p>
                {summary.savings_percentage != null
                  ? `${formatPercentage(summary.savings_percentage)} of the estimated premium-model baseline across ${formatInteger(summary.total_requests)} requests.`
                  : `Across ${formatInteger(summary.total_requests)} requests in this reporting period.`}
              </p>
              <div className="cost-basis-note">
                <span>Cost evidence</span>
                <strong>
                  {formatInteger(summary.actual_cost_savings_request_count)} based on actual API cost
                  {" · "}
                  {formatInteger(summary.estimated_savings_request_count)} estimated
                </strong>
              </div>
            </div>
            <div className="analytics-hero-facts">
              <HeroFact
                label="Requests analyzed"
                value={formatInteger(summary.total_requests)}
                detail={`${formatInteger(summary.completed_requests)} completed · ${formatInteger(summary.blocked_requests)} blocked safely`}
              />
              <HeroFact
                label="Actual API cost"
                value={formatMoney(summary.total_actual_api_cost)}
                detail={
                  summary.total_actual_api_cost === 0
                    ? "Local model execution; no external API charge"
                    : "Measured provider API charges"
                }
              />
              <HeroFact
                label="Estimated premium baseline"
                value={formatMoney(summary.total_estimated_baseline_cost)}
                detail="Comparison baseline, not an invoice"
              />
            </div>
          </section>

          <section className="operating-cards" aria-label="Operating signals">
            <SignalCard
              label="Cache reuse"
              value={formatRate(summary.cache_hit_rate)}
              detail={`${formatRequestCount(summary.cache_hit_rate * summary.total_requests)} avoided a model call`}
              tone="positive"
            />
            <SignalCard
              label="Guardrail blocks"
              value={formatRate(summary.guardrail_block_rate)}
              detail={`${formatRequestCount(summary.blocked_requests)} stopped before unsafe or unnecessary execution`}
              tone="warning"
            />
            <SignalCard
              label="Fallback usage"
              value={formatRate(summary.fallback_rate)}
              detail="Requests completed using an alternate configured provider"
              tone="neutral"
            />
            <SignalCard
              label="Average model latency"
              value={formatLatency(summary.average_latency_ms)}
              detail="Measured executions only"
              tone="info"
            />
          </section>

          <div className="analytics-panels">
            <section className="analytics-panel">
              <PanelHeading
                eyebrow="Efficiency drivers"
                title="Where cost avoidance came from"
                detail="One primary source per request; no double counting."
              />
              <div className="breakdown-list">
                {savingsSources.map((row) => (
                  <BreakdownRow
                    key={row.source}
                    label={sourceLabel(row.source)}
                    value={row.savings}
                    maximum={maxSourceSavings}
                    displayValue={formatMoney(row.savings)}
                    detail={formatRequestCount(row.requests)}
                  />
                ))}
              </div>
            </section>

            <section className="analytics-panel">
              <PanelHeading
                eyebrow="Policy behavior"
                title="Usage by optimization mode"
                detail="Request mix and modeled avoidance for each active policy."
              />
              <div className="breakdown-list policy-breakdown">
                {policyRows.map((row) => (
                  <BreakdownRow
                    key={row.mode}
                    label={row.mode}
                    value={row.requests}
                    maximum={maxPolicyRequests}
                    displayValue={formatInteger(row.requests)}
                    detail={`${formatMoney(row.savings)} avoided`}
                  />
                ))}
              </div>
            </section>
          </div>

          <section className="operations-panel">
            <PanelHeading
              eyebrow="Technical operating context"
              title="What happened behind the outcomes"
              detail="Supporting metrics for diagnosis, not primary financial claims."
            />
            <div className="operations-grid">
              <OperationFact
                label="Input tokens"
                value={formatInteger(summary.total_input_tokens)}
              />
              <OperationFact
                label="Output tokens"
                value={formatInteger(summary.total_output_tokens)}
              />
              <OperationFact
                label="Premium requested"
                value={formatRate(summary.premium_requested_rate)}
              />
              <OperationFact
                label="Premium executed"
                value={formatRate(summary.premium_usage_rate)}
              />
              <OperationFact
                label="Unknown actual cost"
                value={formatInteger(summary.unknown_actual_cost_request_count)}
              />
              <OperationFact
                label="Estimated optimized cost"
                value={formatMoney(summary.total_estimated_optimized_cost)}
              />
            </div>
          </section>

          <section className="roi-panel">
            <div className="roi-copy">
              <span className="page-eyebrow">Optional planning scenario</span>
              <h2>ROI scenario</h2>
              <p>
                Compare modeled cost avoidance with an operating-cost assumption
                for this {periodDays}-day period. This is a planning calculation,
                not realized financial return.
              </p>
              <form className="roi-form" onSubmit={calculateRoi}>
                <label>
                  <span>Operating cost for this period (USD)</span>
                  <input
                    type="number"
                    min="0"
                    step="any"
                    inputMode="decimal"
                    value={operatingCostInput}
                    onChange={(event) => setOperatingCostInput(event.target.value)}
                    placeholder="For example, 0.01"
                    aria-describedby={roiInputError ? "roi-input-error" : undefined}
                  />
                </label>
                <div className="roi-actions">
                  <button className="secondary-button" type="submit">
                    Calculate scenario
                  </button>
                  {appliedOperatingCost != null && (
                    <button
                      className="text-button"
                      type="button"
                      onClick={clearRoiScenario}
                    >
                      Clear
                    </button>
                  )}
                </div>
              </form>
              {roiInputError && (
                <small className="field-error" id="roi-input-error">
                  {roiInputError}
                </small>
              )}
            </div>
            <div
              className={`roi-result ${
                summary.roi_percentage == null
                  ? "neutral"
                  : summary.roi_percentage >= 0
                    ? "positive"
                    : "negative"
              }`}
            >
              <span>Scenario result</span>
              <strong>
                {summary.roi_percentage == null
                  ? "Not calculated"
                  : formatPercentage(summary.roi_percentage)}
              </strong>
              <p>
                {summary.roi_percentage == null
                  ? "Add an explicit operating cost to calculate ROI without treating local API cost as total product cost."
                  : `${formatMoney(summary.total_modeled_cost_avoidance)} modeled avoidance minus ${formatMoney(summary.operating_cost_usd ?? 0)} supplied operating cost.`}
              </p>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function HeroFact({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="hero-fact">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function SignalCard({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail: string;
  tone: "positive" | "warning" | "neutral" | "info";
}) {
  return (
    <div className={`signal-card ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function PanelHeading({
  eyebrow,
  title,
  detail,
}: {
  eyebrow: string;
  title: string;
  detail: string;
}) {
  return (
    <header className="panel-heading">
      <span>{eyebrow}</span>
      <h2>{title}</h2>
      <p>{detail}</p>
    </header>
  );
}

function BreakdownRow({
  label,
  value,
  maximum,
  displayValue,
  detail,
}: {
  label: string;
  value: number;
  maximum: number;
  displayValue: string;
  detail: string;
}) {
  const percentage = maximum > 0 ? (value / maximum) * 100 : 0;
  const width = value > 0 ? Math.max(4, percentage) : 0;
  return (
    <div className="breakdown-row">
      <div className="breakdown-label">
        <strong>{label}</strong>
        <span>{detail}</span>
      </div>
      <div className="breakdown-value">
        <strong>{displayValue}</strong>
        <div className="breakdown-track" aria-hidden="true">
          <span style={{ width: `${width}%` }} />
        </div>
      </div>
    </div>
  );
}

function OperationFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="operation-fact">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
