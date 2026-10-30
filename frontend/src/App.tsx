import { lazy, Suspense } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { TopBar } from "./components/TopBar";
import { StatusBar } from "./components/StatusBar";
import { TokenGate } from "./components/TokenGate";
import Workspace from "./pages/Workspace";
import SchemaExplorer from "./pages/SchemaExplorer";
import Statistics from "./pages/Statistics";
import History from "./pages/History";
import Workload from "./pages/Workload";
import IndexLab from "./pages/IndexLab";
import Lab from "./pages/Lab";

const Landing = lazy(() => import("./landing/Landing"));

export const NAV = [
  { to: "/app", label: "Workspace", end: true },
  { to: "/app/schema", label: "Schema" },
  { to: "/app/statistics", label: "Statistics" },
  { to: "/app/workload", label: "Workloads" },
  { to: "/app/index-lab", label: "Index Lab" },
  { to: "/app/lab", label: "Lab" },
  { to: "/app/history", label: "History" },
];

export default function App() {
  return (
    <>
    <TokenGate />
    <Routes>
      <Route path="/" element={<Suspense fallback={null}><div className="h-screen"><Landing /></div></Suspense>} />
      <Route path="/app/*" element={<Workbench />} />
    </Routes>
    </>
  );
}

function Workbench() {
  return (
    <div className="flex h-screen flex-col">
      <TopBar />
      <nav aria-label="Sections" className="sticky top-14 z-20 shrink-0 overflow-x-auto border-b border-line bg-[color:var(--bg)]">
        <ul className="mx-auto flex max-w-[1360px] min-w-max px-2 sm:px-6">
          {NAV.map((n, i) => (
            <li key={n.to}>
              <NavLink
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  `-mb-px flex items-baseline gap-2 border-b-2 px-3.5 py-3 font-mono text-2xs font-semibold uppercase tracking-[0.14em] transition-colors
                   focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--ring)] ${
                    isActive ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink"
                  }`
                }
              >
                <span className="text-accent">{String(i + 1).padStart(2, "0")}</span>
                {n.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      <main className="min-w-0 flex-1 overflow-y-auto">
        <Routes>
          <Route index element={<Workspace />} />
          <Route path="schema" element={<Page><SchemaExplorer /></Page>} />
          <Route path="statistics" element={<Page><Statistics /></Page>} />
          <Route path="workload" element={<Page><Workload /></Page>} />
          <Route path="index-lab" element={<Page><IndexLab /></Page>} />
          <Route path="lab" element={<Page><Lab /></Page>} />
          <Route path="history" element={<Page><History /></Page>} />
        </Routes>
      </main>
      <StatusBar />
    </div>
  );
}

function Page({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto max-w-[1360px] animate-fade-in px-4 py-8 sm:px-6">{children}</div>;
}
