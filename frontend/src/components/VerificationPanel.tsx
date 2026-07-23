import { useState, type FormEvent } from "react";
import type {
  VerificationStatus,
  VerificationType,
} from "../types";

type OutcomeChoice =
  | "succeeded"
  | "partially_succeeded"
  | "retry"
  | "failed";
type CheckChoice = "not_run" | "passed" | "failed";

export interface VerificationSubmission {
  outcome: OutcomeChoice;
  checks: {
    verification_type: VerificationType;
    status: VerificationStatus;
  }[];
  details: string | null;
}

interface Props {
  attemptNumber: number | null;
  loading: boolean;
  error: string | null;
  onVerify: (submission: VerificationSubmission) => Promise<void>;
}

const OUTCOMES: {
  value: OutcomeChoice;
  label: string;
  description: string;
}[] = [
  {
    value: "succeeded",
    label: "Objective achieved",
    description: "The result meets the coding objective.",
  },
  {
    value: "partially_succeeded",
    label: "Useful partial result",
    description: "Useful progress, but acceptance criteria remain.",
  },
  {
    value: "retry",
    label: "Needs another attempt",
    description: "Record this attempt and continue the same session.",
  },
  {
    value: "failed",
    label: "End as unsuccessful",
    description: "Close the session without a successful outcome.",
  },
];

const CHECKS: { type: VerificationType; label: string }[] = [
  { type: "tests", label: "Tests" },
  { type: "build", label: "Build" },
  { type: "lint", label: "Lint" },
  { type: "type_check", label: "Type check" },
];

export default function VerificationPanel({
  attemptNumber,
  loading,
  error,
  onVerify,
}: Props) {
  const [outcome, setOutcome] = useState<OutcomeChoice>("succeeded");
  const [checks, setChecks] = useState<Record<string, CheckChoice>>({});
  const [details, setDetails] = useState("");
  const hasFailedCheck = Object.values(checks).some(
    (status) => status === "failed",
  );
  const contradictory =
    hasFailedCheck &&
    (outcome === "succeeded" || outcome === "partially_succeeded");

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (loading || contradictory) return;
    await onVerify({
      outcome,
      checks: CHECKS.flatMap(({ type }) => {
        const status = checks[type] ?? "not_run";
        return status === "not_run"
          ? []
          : [{ verification_type: type, status }];
      }),
      details: details.trim() || null,
    });
  }

  return (
    <form
      className="verification-panel"
      onSubmit={handleSubmit}
      aria-busy={loading}
    >
      <header className="verification-header">
        <div>
          <span className="receipt-eyebrow">Outcome evidence</span>
          <h3>Did this attempt complete the coding objective?</h3>
          <p>
            Your feedback unlocks an evidence-labeled Model Fit assessment.
            Attempt {attemptNumber ?? "not recorded"} is awaiting verification.
          </p>
        </div>
        <span className="evidence-source-pill">User-reported</span>
      </header>

      <fieldset className="outcome-options">
        <legend>Outcome</legend>
        {OUTCOMES.map((option) => (
          <label
            className={
              outcome === option.value
                ? "outcome-option selected"
                : "outcome-option"
            }
            key={option.value}
          >
            <input
              type="radio"
              name="coding-outcome"
              value={option.value}
              checked={outcome === option.value}
              disabled={loading}
              onChange={() => setOutcome(option.value)}
            />
            <span>
              <strong>{option.label}</strong>
              <small>{option.description}</small>
            </span>
          </label>
        ))}
      </fieldset>

      <details className="verification-evidence-details">
        <summary>
          <span>
            <strong>Add verification evidence</strong>
            <small>Optional tests, build, lint, type-check, and notes</small>
          </span>
          <span>Optional</span>
        </summary>
        <div className="verification-evidence-content">
          <fieldset className="verification-checks">
            <legend>Checks performed</legend>
            <p>
              These are manual reports. Automated connector evidence will carry
              stronger confidence in a later milestone.
            </p>
            <div className="check-grid">
              {CHECKS.map((check) => (
                <label key={check.type}>
                  <span>{check.label}</span>
                  <select
                    value={checks[check.type] ?? "not_run"}
                    disabled={loading}
                    onChange={(event) =>
                      setChecks((current) => ({
                        ...current,
                        [check.type]: event.target.value as CheckChoice,
                      }))
                    }
                  >
                    <option value="not_run">Not reported</option>
                    <option value="passed">Passed</option>
                    <option value="failed">Failed</option>
                  </select>
                </label>
              ))}
            </div>
          </fieldset>

          <label className="verification-notes">
            <span>Optional note</span>
            <textarea
              rows={2}
              maxLength={500}
              value={details}
              disabled={loading}
              placeholder="What worked, or what still needs attention?"
              onChange={(event) => setDetails(event.target.value)}
            />
          </label>
        </div>
      </details>

      {contradictory && (
        <p className="verification-inline-error" role="alert">
          A failed check cannot be submitted as success or partial success.
          Choose another attempt or end the session as unsuccessful.
        </p>
      )}
      {error && (
        <p className="verification-inline-error" role="alert">{error}</p>
      )}

      <div className="verification-submit">
        <span>
          Scores remain provisional until stronger independent evidence exists.
        </span>
        <button
          className="primary"
          type="submit"
          disabled={loading || contradictory}
        >
          {loading ? "Evaluating..." : "Record outcome"}
        </button>
      </div>
    </form>
  );
}
