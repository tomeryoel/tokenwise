import type { PolicyMode } from "../types";

interface Props {
  policyMode: PolicyMode;
  setPolicyMode: (m: PolicyMode) => void;
  persistenceAvailable: boolean;
}

const MODE_INFO: Record<PolicyMode, string> = {
  conservative:
    "Prioritizes quality. Prefers stronger model tiers and avoids compression unless the request is very large.",
  balanced:
    "Balances quality and savings. Uses task complexity, prompt size, and risk to choose an appropriate tier.",
  aggressive:
    "Maximizes savings. Favors cheaper tiers and earlier compression when safe; guardrails and privacy still take priority.",
};

const MODES: PolicyMode[] = ["conservative", "balanced", "aggressive"];

export default function Admin({
  policyMode,
  setPolicyMode,
  persistenceAvailable,
}: Props) {
  return (
    <div className="page policy-page">
      <span className="page-eyebrow">Local policy control</span>
      <h1>Optimization policy</h1>
      <p className="policy-intro">
        Choose how TokenWise balances answer quality and savings. Every
        Playground request uses the active mode, while safety and privacy rules
        always remain enforced.
      </p>

      <div
        className={
          persistenceAvailable
            ? "policy-save-state saved"
            : "policy-save-state session-only"
        }
        role="status"
      >
        <span className="policy-save-dot" aria-hidden="true" />
        <div>
          <strong>Active policy: {policyMode}</strong>
          <span>
            {persistenceAvailable
              ? "Saved on this device and applied to Playground requests."
              : "Applied for this session, but browser storage is unavailable."}
          </span>
        </div>
      </div>

      <div className="policy-section-heading">
        <div>
          <span>Routing behavior</span>
          <h2>Select an optimization mode</h2>
        </div>
        <small>Changes apply immediately</small>
      </div>

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
              <div className="mode-title">
                {m}
                {m === "balanced" && <span>Recommended</span>}
              </div>
              <div className="mode-desc">{MODE_INFO[m]}</div>
            </div>
          </label>
        ))}
      </div>
    </div>
  );
}
