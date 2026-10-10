import { NavLink, Route, Routes } from "react-router-dom";
import { useStore } from "./store";
import Overview from "./pages/Overview";
import Optimizer from "./pages/Optimizer";
import RelationalAlgebra from "./pages/RelationalAlgebra";
import ExecutionPlans from "./pages/ExecutionPlans";
import CandidatePlans from "./pages/CandidatePlans";
import SchemaExplorer from "./pages/SchemaExplorer";
import Statistics from "./pages/Statistics";
import IndexAdvisor from "./pages/IndexAdvisor";
import TursoComparison from "./pages/TursoComparison";
import Copilot from "./pages/Copilot";
import History from "./pages/History";

const NAV = [
  { to: "/", label: "Overview", icon: "▤", end: true },
  { to: "/optimizer", label: "SQL Optimizer", icon: "⚡" },
  { to: "/relational-algebra", label: "Relational Algebra", icon: "𝛑" },
  { to: "/execution-plans", label: "Execution Plans", icon: "🌳" },
  { to: "/candidate-plans", label: "Candidate Plans", icon: "▦" },
  { to: "/schema", label: "Schema Explorer", icon: "🗄" },
  { to: "/statistics", label: "Statistics", icon: "📊" },
  { to: "/index-advisor", label: "Index Advisor", icon: "🔑" },
  { to: "/turso-comparison", label: "Turso Plan Comparison", icon: "⇄" },
  { to: "/copilot", label: "AI Copilot", icon: "🤖" },
  { to: "/history", label: "Query History", icon: "🕘" },
];

export default function App() {
  const { theme, toggleTheme, result, loading } = useStore();
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-64 flex-col border-r border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="px-4 py-4">
          <div className="text-sm font-bold leading-tight">SQL Query Optimizer</div>
          <div className="text-xs text-slate-500">Cost-based · Turso / libSQL</div>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto px-2">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${
                  isActive
                    ? "bg-brand-600 text-white"
                    : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                }`
              }
            >
              <span className="w-5 text-center">{n.icon}</span>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-200 p-3 text-xs dark:border-slate-800">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-slate-500">Loaded query</span>
            <span className={`badge ${loading ? "bg-amber-100 text-amber-800" : result ? "bg-green-100 text-green-700" : "bg-slate-100 text-slate-600"}`}>
              {loading ? "running" : result ? "ready" : "none"}
            </span>
          </div>
          <button className="btn btn-ghost w-full justify-center" onClick={toggleTheme}>
            {theme === "dark" ? "☀ Light mode" : "🌙 Dark mode"}
          </button>
        </div>
      </aside>

      <main className="flex-1 overflow-x-hidden">
        <div className="mx-auto max-w-7xl p-6">
          <Routes>
            <Route path="/" element={<Overview />} />
            <Route path="/optimizer" element={<Optimizer />} />
            <Route path="/relational-algebra" element={<RelationalAlgebra />} />
            <Route path="/execution-plans" element={<ExecutionPlans />} />
            <Route path="/candidate-plans" element={<CandidatePlans />} />
            <Route path="/schema" element={<SchemaExplorer />} />
            <Route path="/statistics" element={<Statistics />} />
            <Route path="/index-advisor" element={<IndexAdvisor />} />
            <Route path="/turso-comparison" element={<TursoComparison />} />
            <Route path="/copilot" element={<Copilot />} />
            <Route path="/history" element={<History />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
