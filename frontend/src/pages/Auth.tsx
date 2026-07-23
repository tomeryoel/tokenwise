import { useState, type FormEvent } from "react";
import { login, setupOwner } from "../api";
import { PRODUCT_NAME } from "../brand";
import type { AuthState } from "../types";

interface Props {
  setupRequired: boolean;
  onAuthenticated: (state: AuthState) => void;
}

export default function Auth({ setupRequired, onAuthenticated }: Props) {
  const [displayName, setDisplayName] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [departmentId, setDepartmentId] = useState("general");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const state = setupRequired
        ? await setupOwner({
            display_name: displayName,
            organization_name: organizationName,
            department_id: departmentId,
            email,
            password,
          })
        : await login(email, password);
      onAuthenticated(state);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-story">
        <div className="auth-brand">{PRODUCT_NAME}</div>
        <span className="auth-kicker">The control plane for AI spend</span>
        <h1>Know why every model call happened.</h1>
        <p>
          Route requests by policy, protect sensitive inputs, reuse trusted
          answers, and see the cost decision behind every response.
        </p>
        <div className="auth-proof">
          <span>Private by default</span>
          <span>Organization-scoped data</span>
          <span>Visible optimization receipts</span>
        </div>
      </section>

      <section className="auth-panel">
        <div className="auth-panel-heading">
          <span>{setupRequired ? "First-run setup" : "Welcome back"}</span>
          <h2>{setupRequired ? "Create the owner account" : "Sign in to continue"}</h2>
          <p>
            {setupRequired
              ? "This account controls your organization's policy and dashboard."
              : "Use your MomiHelm account to access protected usage data."}
          </p>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          {setupRequired && (
            <>
              <label>
                <span>Your name</span>
                <input
                  required
                  minLength={2}
                  maxLength={80}
                  autoComplete="name"
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  placeholder="Tomer Yoel"
                />
              </label>
              <label>
                <span>Organization</span>
                <input
                  required
                  minLength={2}
                  maxLength={100}
                  autoComplete="organization"
                  value={organizationName}
                  onChange={(event) => setOrganizationName(event.target.value)}
                  placeholder="Your company or team"
                />
              </label>
              <label>
                <span>Department</span>
                <input
                  required
                  maxLength={80}
                  value={departmentId}
                  onChange={(event) => setDepartmentId(event.target.value)}
                  placeholder="general"
                />
              </label>
            </>
          )}
          <label>
            <span>Email</span>
            <input
              required
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@company.com"
            />
          </label>
          <label>
            <span>Password</span>
            <input
              required
              type="password"
              minLength={setupRequired ? 12 : 1}
              maxLength={128}
              autoComplete={setupRequired ? "new-password" : "current-password"}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={setupRequired ? "At least 12 characters" : "Your password"}
            />
          </label>

          {error && <div className="auth-error" role="alert">{error}</div>}

          <button className="auth-submit" type="submit" disabled={submitting}>
            {submitting
              ? "Please wait..."
              : setupRequired
                ? "Create owner account"
                : "Sign in"}
          </button>
        </form>

        <small className="auth-security-note">
          Session cookies are HTTP-only. Passwords are stored as Argon2id hashes.
        </small>
      </section>
    </main>
  );
}
