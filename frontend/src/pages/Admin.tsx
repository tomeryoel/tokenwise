import type { PolicyMode } from "../types";

interface Props {
  policyMode: PolicyMode;
  setPolicyMode: (m: PolicyMode) => void;
}

const MODE_INFO: Record<PolicyMode, string> = {
  conservative:
    "Minimal interference. Prefers safer/stronger tiers, fewer downgrades. Higher cost, smoothest workflow.",
  balanced:
    "Default. Reasonable savings vs quality: cheap tier for short prompts, balanced tier for larger ones.",
  aggressive:
    "Maximise savings. Prefers the cheap tier and (later) more compression and cache reuse. Lower cost, more downgrades.",
};

const MODES: PolicyMode[] = ["conservative", "balanced", "aggressive"];

export default function Admin({ policyMode, setPolicyMode }: Props) {
  return (
    <div className="page">
      <h1>Admin / Policy</h1>
      <p className="muted">
        Choose how aggressive TokenWise is. This mode is shared with the
        Playground and (later) drives routing, compression and cache thresholds.
      </p>

      <div className="mode-list">
        {MODES.map((m) => (
          <label
            key={m}
            className={m === policyMode ? "mode-card selected" : "mode-card"}
          >
            <input
              type="radio"
              name="policy-mode"
              checked={m === policyMode}
              onChange={() => setPolicyMode(m)}
            />
            <div>
              <div className="mode-title">{m}</div>
              <div className="mode-desc">{MODE_INFO[m]}</div>
            </div>
          </label>
        ))}
      </div>
    </div>
  );
}
