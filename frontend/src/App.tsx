import { useState } from "react";
import type { PolicyMode } from "./types";
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
  // Policy mode is shared: the Admin page and the Playground selector stay in sync.
  const [policyMode, setPolicyMode] = useState<PolicyMode>("balanced");

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">TokenWise</div>
        <nav className="nav">
          {TABS.map((t) => (
            <button
              key={t.id}
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
          <Playground policyMode={policyMode} setPolicyMode={setPolicyMode} />
        )}
        {tab === "dashboard" && <Dashboard />}
        {tab === "admin" && (
          <Admin policyMode={policyMode} setPolicyMode={setPolicyMode} />
        )}
      </main>
    </div>
  );
}
