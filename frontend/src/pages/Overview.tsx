import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmt } from "../api";
import { Card, Loading, Stat } from "../components/ui";
import { useStore } from "../store";

const FLOW = [
  "Turso / libSQL", "Schema Discovery", "Statistics", "SQL Parser", "Relational Algebra",
  "Selectivity", "Cardinality", "Candidate Plans", "Cost Model", "Best Plan",
  "Logical Rewrites", "Turso EXPLAIN", "Benchmark", "Index Advisor", "AI Explanation",
];

export default function Overview() {
  const [health, setHealth] = useState<any>(null);
  const [cfg, setCfg] = useState<any>(null);
  const { result } = useStore();

  useEffect(() => {
    api.health().then(setHealth).catch(() => {});
    api.config().then(setCfg).catch(() => {});
  }, []);

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold">AI-Powered Cost-Based SQL Query Optimizer</h1>
        <p className="text-sm text-slate-500">
          A schema-agnostic query optimizer & performance analyzer running on Turso / libSQL.
          Every number below is computed from the live database — nothing is hardcoded.
        </p>
      </header>

      {!health ? <Loading label="Connecting to backend…" /> : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Database backend" value={<span className="text-base">{health.database_backend}</span>} />
          <Stat label="Tables discovered" value={fmt(health.tables?.length, 0)} sub={health.tables?.join(", ")} />
          <Stat label="AI Copilot" value={health.openai_configured ? "OpenAI" : "Offline"} sub={health.openai_configured ? "API configured" : "template fallback"} />
          <Stat label="Optimizer" value={`v${cfg?.optimizer_version ?? "—"}`} sub="cost-based" />
        </div>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card title="Pipeline data flow" className="lg:col-span-2">
          <div className="flex flex-wrap items-center gap-2">
            {FLOW.map((step, i) => (
              <span key={step} className="flex items-center gap-2">
                <span className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium dark:border-slate-800 dark:bg-slate-950">
                  {step}
                </span>
                {i < FLOW.length - 1 && <span className="text-slate-400">→</span>}
              </span>
            ))}
          </div>
          <div className="mt-4">
            <Link to="/optimizer" className="btn btn-primary">⚡ Open the SQL Optimizer</Link>
          </div>
        </Card>

        <Card title="Cost model constants">
          {!cfg ? <Loading /> : (
            <table className="data">
              <tbody>
                <tr><td>I/O per page</td><td className="text-right">{cfg.cost_model.cost_io_per_page}</td></tr>
                <tr><td>CPU per row</td><td className="text-right">{cfg.cost_model.cost_cpu_per_row}</td></tr>
                <tr><td>CPU per operator</td><td className="text-right">{cfg.cost_model.cost_cpu_per_operator}</td></tr>
                <tr><td>Rows per page</td><td className="text-right">{cfg.cost_model.rows_per_page}</td></tr>
                <tr><td>Default eq selectivity</td><td className="text-right">{cfg.selectivity_defaults.equality}</td></tr>
                <tr><td>Default range selectivity</td><td className="text-right">{cfg.selectivity_defaults.range}</td></tr>
              </tbody>
            </table>
          )}
        </Card>
      </div>

      {result && (
        <Card title="Last optimized query">
          <pre className="overflow-x-auto rounded-lg bg-slate-50 p-3 text-xs dark:bg-slate-950">{result.sql}</pre>
          <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Selected cost" value={fmt(result.summary.selected_total_cost)} />
            <Stat label="Est. rows" value={fmt(result.summary.estimated_cardinality, 0)} />
            <Stat label="Candidates" value={fmt(result.summary.candidate_count, 0)} />
            <Stat label="Statistics source" value={<span className="text-sm">{result.statistics_source}</span>} />
          </div>
        </Card>
      )}
    </div>
  );
}
