import { useState, type FormEvent } from "react";
import { changePassword } from "../api";
import type { AuthUser } from "../types";

export default function Account({ user }: { user: AuthUser }) {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (saving) return;
    if (newPassword !== confirmation) {
      setError("The new passwords do not match.");
      return;
    }
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      await changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmation("");
      setSuccess(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Password update failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page account-page">
      <span className="page-eyebrow">Signed-in identity</span>
      <h1>Account</h1>
      <section className="account-card">
        <div className="account-profile">
          <span className="account-avatar" aria-hidden="true">
            {user.display_name.charAt(0).toUpperCase()}
          </span>
          <div>
            <h2>{user.display_name}</h2>
            <p>{user.email}</p>
          </div>
          <dl>
            <div><dt>Organization</dt><dd>{user.organization_name}</dd></div>
            <div><dt>Department</dt><dd>{user.department_id}</dd></div>
            <div><dt>Role</dt><dd>{user.role}</dd></div>
          </dl>
        </div>

        <form className="account-password-form" onSubmit={handleSubmit}>
          <div>
            <span>Security</span>
            <h2>Change password</h2>
            <p>Changing it revokes your other active sessions.</p>
          </div>
          <label>
            <span>Current password</span>
            <input
              required
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
            />
          </label>
          <label>
            <span>New password</span>
            <input
              required
              type="password"
              minLength={12}
              maxLength={128}
              autoComplete="new-password"
              value={newPassword}
              onChange={(event) => setNewPassword(event.target.value)}
              placeholder="At least 12 characters"
            />
          </label>
          <label>
            <span>Confirm new password</span>
            <input
              required
              type="password"
              minLength={12}
              maxLength={128}
              autoComplete="new-password"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
            />
          </label>
          {error && <div className="auth-error" role="alert">{error}</div>}
          {success && (
            <div className="account-success" role="status">
              Password updated. Other sessions were signed out.
            </div>
          )}
          <button className="secondary-button" type="submit" disabled={saving}>
            {saving ? "Updating password..." : "Update password"}
          </button>
        </form>
      </section>
    </div>
  );
}
