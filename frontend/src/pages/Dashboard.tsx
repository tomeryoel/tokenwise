import { useEffect, useState } from "react";
import { fetchUsageSummary, type UsageSummary } from "../api";

function pct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

function money(value: number): string {
  return `$${value.toFixed(4)}`;
}

function ms(value: number): string {
  return `${Math.round(value)} ms`;
}

export default function Dashboard() {
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deptId, setDeptId] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchUsageSummary(deptId || undefined)
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
  }, [deptId]);

  const cards = summary
    ? [
        { label: "Total Requests", value: String(summary.total_requests) },
        { label: "Realized Savings", value: money(summary.total_savings) },
        { label: "Cache Hit Rate", value: pct(summary.cache_hit_rate) },
        { label: "Guardrail Block Rate", value: pct(summary.guardrail_block_rate) },
        { label: "Premium Usage", value: pct(summary.premium_usage_rate) },
        { label: "Average Latency", value: ms(summary.average_latency_ms) },
      ]
    : [];

  return (
    <div className="page">
      <h1>Dashboard</h1>

      <div style={{ marginBottom: "1rem" }}>
        <label>
          Department filter (optional):{" "}
          <input
            value={deptId}
            onChange={(e) => setDeptId(e.target.value)}
            placeholder="all departments"
          />
        </label>
      </div>

      {loading && <div className="banner-info">Loading usage analytics…</div>}
      {error && (
        <div className="banner-info">
          Usage analytics unavailable: {error}
        </div>
      )}
      {!loading && !error && summary && summary.total_requests === 0 && (
        <div className="banner-info">
          No usage data yet. Run requests through the Playground to populate the database.
        </div>
      )}

      {!loading && !error && summary && summary.total_requests > 0 && (
        <>
          <div className="cards">
            {cards.map((m) => (
              <div key={m.label} className="card">
                <div className="card-value">{m.value}</div>
                <div className="card-label">{m.label}</div>
              </div>
            ))}
          </div>

          <div style={{ marginTop: "1.5rem" }}>
            <h2>Savings by Source</h2>
            <ul>
              {Object.entries(summary.savings_by_source)
                .filter(([, v]) => v > 0)
                .map(([source, amount]) => (
                  <li key={source}>
                    {source}: {money(amount)}
                  </li>
                ))}
            </ul>
          </div>

          <div style={{ marginTop: "1rem" }}>
            <h2>Requests by Source</h2>
            <ul>
              {Object.entries(summary.requests_by_source)
                .filter(([, v]) => v > 0)
                .map(([source, count]) => (
                  <li key={source}>
                    {source}: {count}
                  </li>
                ))}
            </ul>
          </div>

          {summary.savings_percentage != null && (
            <p style={{ marginTop: "1rem" }}>
              Savings vs baseline: {summary.savings_percentage.toFixed(1)}% (
              {summary.roi_status})
            </p>
          )}
        </>
      )}
    </div>
  );
}
