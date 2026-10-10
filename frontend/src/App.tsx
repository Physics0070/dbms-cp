import { useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { TopBar } from "./components/TopBar";
import { useStore } from "./store";
import Workspace from "./pages/Workspace";
import SchemaExplorer from "./pages/SchemaExplorer";
import Statistics from "./pages/Statistics";
import History from "./pages/History";

const NAV = [
  { to: "/", label: "Workspace", icon: "⚡", end: true },
  { to: "/schema", label: "Schema", icon: "⬡" },
  { to: "/statistics", label: "Statistics", icon: "▤" },
  { to: "/history", label: "History", icon: "⟲" },
];

export default function App() {
  const { loading, result } = useStore();
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className="flex h-screen flex-col">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        {/* Icon rail on small screens; full labels on md+ (manual collapse on desktop). */}
        <aside
          className={`flex shrink-0 flex-col border-r border-line bg-panel transition-[width] duration-200
            ${collapsed ? "w-[56px]" : "w-[56px] md:w-[208px]"}`}
        >
          <nav className="flex-1 space-y-1 p-2">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                title={n.label}
                className={({ isActive }) =>
                  `flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors ${
                    isActive ? "bg-[color:var(--accent-soft)] text-accent" : "text-muted hover:bg-panel-2 hover:text-ink"
                  }`
                }
              >
                <span className="grid w-5 shrink-0 place-items-center text-base">{n.icon}</span>
                <span className={collapsed ? "hidden" : "hidden md:inline"}>{n.label}</span>
              </NavLink>
            ))}
          </nav>

          <div className="space-y-2 border-t border-line p-2">
            <div className={`items-center justify-between px-1 text-2xs ${collapsed ? "hidden" : "hidden md:flex"}`}>
              <span className="text-faint">Query</span>
              <span className={`chip ${loading ? "bg-[color:var(--warn-soft)] text-warn" : result ? "bg-[color:var(--ok-soft)] text-ok" : "bg-panel-3 text-faint"}`}>
                {loading ? "running" : result ? "ready" : "idle"}
              </span>
            </div>
            <button className="btn btn-subtle hidden w-full justify-center md:flex" onClick={() => setCollapsed((c) => !c)}
              title={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
              {collapsed ? "»" : "« Collapse"}
            </button>
          </div>
        </aside>

        <main className="min-w-0 flex-1 overflow-y-auto">
          <Routes>
            <Route path="/" element={<Workspace />} />
            <Route path="/schema" element={<Page><SchemaExplorer /></Page>} />
            <Route path="/statistics" element={<Page><Statistics /></Page>} />
            <Route path="/history" element={<Page><History /></Page>} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

function Page({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto max-w-6xl animate-fade-in p-6">{children}</div>;
}
