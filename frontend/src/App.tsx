import { useState } from "react";
import type { PolicyMode } from "./types";
import {
  initialPlaygroundSession,
  type PlaygroundSession,
} from "./playgroundSession";
import Playground from "./pages/Playground";
import Dashboard from "./pages/Dashboard";
import Admin from "./pages/Admin";

type Tab = "playground" | "dashboard" | "admin";

const TABS: { id: Tab; label: string }[] = [
  { id: "playground", label: "Playground" },
  { id: "dashboard", label: "Dashboard" },
  { id: "admin", label: "Admin" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("playground");
  const [policyMode, setPolicyMode] = useState<PolicyMode>("balanced");
  const [playgroundSession, setPlaygroundSession] =
    useState<PlaygroundSession>(initialPlaygroundSession());

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">TokenWise</div>
        <nav className="nav">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={tab === t.id ? "nav-btn active" : "nav-btn"}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="content">
        {tab === "playground" && (
          <Playground
            policyMode={policyMode}
            setPolicyMode={setPolicyMode}
            session={playgroundSession}
            setSession={setPlaygroundSession}
          />
        )}
        {tab === "dashboard" && <Dashboard />}
        {tab === "admin" && (
          <Admin policyMode={policyMode} setPolicyMode={setPolicyMode} />
        )}
      </main>
    </div>
  );
}
