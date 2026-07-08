// Dashboard - skeleton uses static mock numbers.
// Real metrics come from the usage DB on Day 10.
const MOCK_METRICS = [
  { label: "Total requests", value: "128" },
  { label: "Estimated total cost", value: "$3.42" },
  { label: "Estimated savings", value: "$9.87" },
  { label: "Cache hit rate", value: "31%" },
  { label: "Premium usage", value: "8%" },
];

export default function Dashboard() {
  return (
    <div className="page">
      <h1>Dashboard</h1>
      <div className="banner-info">
        Mock numbers - wired to the usage database later (Day 10).
      </div>
      <div className="cards">
        {MOCK_METRICS.map((m) => (
          <div key={m.label} className="card">
            <div className="card-value">{m.value}</div>
            <div className="card-label">{m.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
