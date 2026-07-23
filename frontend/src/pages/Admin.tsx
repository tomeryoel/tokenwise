import { useEffect, useState, type FormEvent } from "react";
import { createUser, fetchUsers, updatePolicy } from "../api";
import { PRODUCT_NAME } from "../brand";
import type { AuthUser, PolicyMode } from "../types";

interface Props {
  user: AuthUser;
  onUserUpdated: (user: AuthUser) => void;
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

export default function Admin({ user, onUserUpdated }: Props) {
  const [savingMode, setSavingMode] = useState<PolicyMode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [usersError, setUsersError] = useState<string | null>(null);
  const [creatingUser, setCreatingUser] = useState(false);
  const [newName, setNewName] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newDepartment, setNewDepartment] = useState("general");
  const [newRole, setNewRole] = useState<"admin" | "member">("member");

  useEffect(() => {
    let cancelled = false;
    fetchUsers()
      .then((items) => {
        if (!cancelled) setUsers(items);
      })
      .catch((err: Error) => {
        if (!cancelled) setUsersError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function selectMode(mode: PolicyMode) {
    if (mode === user.policy_mode || savingMode) return;
    setSavingMode(mode);
    setError(null);
    setSaved(false);
    try {
      const updatedUser = await updatePolicy(mode);
      onUserUpdated(updatedUser);
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Policy update failed.");
    } finally {
      setSavingMode(null);
    }
  }

  async function addUser(event: FormEvent) {
    event.preventDefault();
    if (creatingUser) return;
    setCreatingUser(true);
    setUsersError(null);
    try {
      const created = await createUser({
        display_name: newName,
        email: newEmail,
        password: newPassword,
        department_id: newDepartment,
        role: newRole,
      });
      setUsers((current) =>
        [...current, created].sort((a, b) =>
          a.display_name.localeCompare(b.display_name),
        ),
      );
      setNewName("");
      setNewEmail("");
      setNewPassword("");
      setNewDepartment("general");
      setNewRole("member");
    } catch (err) {
      setUsersError(err instanceof Error ? err.message : "Account creation failed.");
    } finally {
      setCreatingUser(false);
    }
  }

  return (
    <div className="page policy-page">
      <span className="page-eyebrow">Organization control</span>
      <h1>Optimization policy</h1>
      <p className="policy-intro">
        Choose how {PRODUCT_NAME} balances answer quality and savings for
        everyone in {user.organization_name}. Safety and privacy rules always
        remain enforced.
      </p>

      <div
        className={`policy-save-state ${error ? "session-only" : "saved"}`}
        role="status"
      >
        <span className="policy-save-dot" aria-hidden="true" />
        <div>
          <strong>Active policy: {user.policy_mode}</strong>
          <span>
            {error
              ? error
              : saved
                ? "Saved to the organization and active for every new request."
                : "Stored on the server and enforced for every signed-in user."}
          </span>
        </div>
      </div>

      <div className="policy-section-heading">
        <div>
          <span>Routing behavior</span>
          <h2>Select an optimization mode</h2>
        </div>
        <small>{savingMode ? `Saving ${savingMode}...` : "Changes apply immediately"}</small>
      </div>

      <div className="mode-list">
        {MODES.map((mode) => (
          <label
            key={mode}
            className={mode === user.policy_mode ? "mode-card selected" : "mode-card"}
          >
            <input
              type="radio"
              name="policy-mode"
              checked={mode === user.policy_mode}
              disabled={savingMode !== null}
              onChange={() => void selectMode(mode)}
            />
            <div>
              <div className="mode-title">
                {mode}
                {mode === "balanced" && <span>Recommended</span>}
              </div>
              <div className="mode-desc">{MODE_INFO[mode]}</div>
            </div>
          </label>
        ))}
      </div>

      <section className="team-section">
        <div className="policy-section-heading">
          <div>
            <span>Access control</span>
            <h2>Organization accounts</h2>
          </div>
          <small>{users.length} active {users.length === 1 ? "account" : "accounts"}</small>
        </div>

        <div className="team-layout">
          <div className="team-list">
            {users.map((account) => (
              <div className="team-member" key={account.id}>
                <span className="user-avatar" aria-hidden="true">
                  {account.display_name.charAt(0).toUpperCase()}
                </span>
                <div>
                  <strong>{account.display_name}</strong>
                  <small>{account.email}</small>
                </div>
                <span className="team-role">{account.role}</span>
                <span className="team-department">{account.department_id}</span>
              </div>
            ))}
          </div>

          <form className="team-form" onSubmit={addUser}>
            <strong>Add an account</strong>
            <p>The new user can sign in immediately with these credentials.</p>
            <label>
              <span>Name</span>
              <input
                required
                minLength={2}
                maxLength={80}
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
                placeholder="Team member name"
              />
            </label>
            <label>
              <span>Email</span>
              <input
                required
                type="email"
                value={newEmail}
                onChange={(event) => setNewEmail(event.target.value)}
                placeholder="member@company.com"
              />
            </label>
            <label>
              <span>Temporary password</span>
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
            <div className="team-form-row">
              <label>
                <span>Department</span>
                <input
                  required
                  maxLength={80}
                  value={newDepartment}
                  onChange={(event) => setNewDepartment(event.target.value)}
                />
              </label>
              <label>
                <span>Role</span>
                <select
                  value={newRole}
                  onChange={(event) =>
                    setNewRole(event.target.value as "admin" | "member")
                  }
                >
                  <option value="member">Member</option>
                  {user.role === "owner" && <option value="admin">Admin</option>}
                </select>
              </label>
            </div>
            {usersError && <div className="auth-error" role="alert">{usersError}</div>}
            <button
              className="secondary-button"
              type="submit"
              disabled={creatingUser}
            >
              {creatingUser ? "Creating account..." : "Create account"}
            </button>
          </form>
        </div>
      </section>
    </div>
  );
}
