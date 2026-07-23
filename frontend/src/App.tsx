import { useEffect, useState } from "react";
import { fetchAuthState, logout } from "./api";
import type { AuthState, AuthUser } from "./types";
import {
  initialPlaygroundSession,
  type PlaygroundSession,
} from "./playgroundSession";
import Auth from "./pages/Auth";
import Playground from "./pages/Playground";
import Dashboard from "./pages/Dashboard";
import Admin from "./pages/Admin";
import Account from "./pages/Account";
import { PRODUCT_NAME } from "./brand";

type Tab = "playground" | "dashboard" | "admin" | "account";

const BASE_TABS: { id: Tab; label: string }[] = [
  { id: "playground", label: "Playground" },
  { id: "dashboard", label: "Dashboard" },
  { id: "admin", label: "Admin" },
  { id: "account", label: "Account" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("playground");
  const [authState, setAuthState] = useState<AuthState | null>(null);
  const [startupError, setStartupError] = useState<string | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);
  const [playgroundSession, setPlaygroundSession] =
    useState<PlaygroundSession>(initialPlaygroundSession());

  useEffect(() => {
    let cancelled = false;
    fetchAuthState()
      .then((state) => {
        if (!cancelled) setAuthState(state);
      })
      .catch((error: Error) => {
        if (!cancelled) setStartupError(error.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleLogout() {
    if (loggingOut) return;
    setLoggingOut(true);
    try {
      await logout();
      setPlaygroundSession(initialPlaygroundSession());
      setTab("playground");
      setAuthState({
        setup_required: false,
        authenticated: false,
        user: null,
      });
    } catch (error) {
      setStartupError(error instanceof Error ? error.message : "Sign out failed.");
    } finally {
      setLoggingOut(false);
    }
  }

  function updateUser(user: AuthUser) {
    setAuthState({
      setup_required: false,
      authenticated: true,
      user,
    });
  }

  if (startupError && authState === null) {
    return (
      <main className="startup-state" role="alert">
        <div className="auth-brand">{PRODUCT_NAME}</div>
        <h1>MomiHelm could not start</h1>
        <p>{startupError}</p>
        <button type="button" onClick={() => window.location.reload()}>
          Try again
        </button>
      </main>
    );
  }

  if (authState === null) {
    return (
      <main className="startup-state" role="status">
        <div className="auth-brand">{PRODUCT_NAME}</div>
        <span className="startup-pulse" />
        <p>Opening your protected workspace...</p>
      </main>
    );
  }

  if (!authState.authenticated || !authState.user) {
    return (
      <Auth
        setupRequired={authState.setup_required}
        onAuthenticated={setAuthState}
      />
    );
  }

  const user = authState.user;
  const tabs = user.can_manage
    ? BASE_TABS
    : BASE_TABS.filter((item) => item.id !== "admin");

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand-lockup">
          <div className="brand">{PRODUCT_NAME}</div>
          <span>{user.organization_name}</span>
        </div>
        <nav className="nav" aria-label="Primary navigation">
          {tabs.map((item) => (
            <button
              key={item.id}
              type="button"
              className={tab === item.id ? "nav-btn active" : "nav-btn"}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="user-menu">
          <span className="user-avatar" aria-hidden="true">
            {user.display_name.charAt(0).toUpperCase()}
          </span>
          <span className="user-identity">
            <strong>{user.display_name}</strong>
            <small>{user.role} · {user.department_id}</small>
          </span>
          <button
            type="button"
            className="signout-button"
            disabled={loggingOut}
            onClick={() => void handleLogout()}
          >
            {loggingOut ? "Signing out..." : "Sign out"}
          </button>
        </div>
      </header>

      {startupError && (
        <div className="global-warning" role="alert">{startupError}</div>
      )}

      <main className="content">
        {tab === "playground" && (
          <Playground
            policyMode={user.policy_mode}
            session={playgroundSession}
            setSession={setPlaygroundSession}
          />
        )}
        {tab === "dashboard" && <Dashboard user={user} />}
        {tab === "admin" && user.can_manage && (
          <Admin user={user} onUserUpdated={updateUser} />
        )}
        {tab === "account" && <Account user={user} />}
      </main>
    </div>
  );
}
