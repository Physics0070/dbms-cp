import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmt, SchemaResponse } from "../api";
import { Card, ErrorState, Loading, Stat } from "../components/ui";
import { useStore } from "../store";

export default function Optimizer() {
  const { sql, setSql, runOptimize, loading, error, result, benchmark, setBenchmark } = useStore();
  const [schema, setSchema] = useState<SchemaResponse | null>(null);
  const [validation, setValidation] = useState<{ valid: boolean; message: string } | null>(null);

  useEffect(() => { api.schema().then(setSchema).catch(() => {}); }, []);

  async function validate() {
    try { setValidation(await api.validate(sql)); } catch (e: any) { setValidation({ valid: false, message: e.message }); }
  }

  const s = result?.summary;

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold">SQL Optimizer</h1>
        <p className="text-sm text-slate-500">Parse, cost, and optimize a read-only query against the live Turso/libSQL database.</p>
      </header>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-3">
          <Card title="Query editor">
            <textarea
              className="h-56 w-full resize-y rounded-lg border border-slate-300 bg-slate-50 p-3 font-mono text-sm outline-none focus:border-brand-500 dark:border-slate-700 dark:bg-slate-950"
              value={sql}
              spellCheck={false}
              onChange={(e) => { setSql(e.target.value); setValidation(null); }}
            />
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <button className="btn btn-primary" onClick={runOptimize} disabled={loading}>
                {loading ? "Optimizing…" : "⚡ Optimize"}
              </button>
              <button className="btn btn-ghost" onClick={validate} disabled={loading}>Validate</button>
              <label className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
                <input type="checkbox" checked={benchmark} onChange={(e) => setBenchmark(e.target.checked)} />
                Run application benchmark
              </label>
            </div>
            {validation && (
              <div className={`mt-3 rounded-lg px-3 py-2 text-sm ${validation.valid ? "bg-green-50 text-green-700 dark:bg-green-950/40 dark:text-green-300" : "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300"}`}>
                {validation.valid ? "✓ " : "✕ "}{validation.message}
              </div>
            )}
            {error && <div className="mt-3"><ErrorState message={error} /></div>}
          </Card>

          {loading && <Card><Loading label="Running the full optimizer pipeline…" /></Card>}

          {result && !loading && (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Stat label="Selected cost" value={fmt(s.selected_total_cost)} sub="abstract units" />
                <Stat label="Est. cardinality" value={fmt(s.estimated_cardinality, 0)} sub="rows" />
                <Stat label="Candidates" value={fmt(s.candidate_count, 0)} sub={`${fmt(s.join_orders_considered,0)} orders considered`} />
                <Stat label="Optimize time" value={`${fmt(result.optimization_time_ms)} ms`} sub="pipeline wall-clock" />
              </div>
              <Card title="Why this plan won">
                <p className="text-sm">{result.optimization.reason}</p>
                <div className="mt-3 flex flex-wrap gap-2 text-sm">
                  <Link className="btn btn-ghost" to="/execution-plans">View execution tree →</Link>
                  <Link className="btn btn-ghost" to="/candidate-plans">Compare candidates →</Link>
                  <Link className="btn btn-ghost" to="/relational-algebra">Relational algebra →</Link>
                  <Link className="btn btn-ghost" to="/copilot">Explain with AI →</Link>
                </div>
                {result.benchmark && !result.benchmark.error && (
                  <div className="mt-3 rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-950">
                    <span className="font-semibold">Application Benchmark</span> (separate from cost estimate):
                    median <b>{fmt(result.benchmark.median_ms)} ms</b>, avg {fmt(result.benchmark.avg_ms)} ms,
                    over {result.benchmark.measured_runs} runs, {fmt(result.benchmark.rows_returned, 0)} rows.
                  </div>
                )}
              </Card>
            </>
          )}
        </div>

        <div className="space-y-3">
          <Card title="Schema browser" right={<Link to="/schema" className="text-xs text-brand-600 hover:underline">Explore →</Link>}>
            {!schema ? <Loading label="Loading schema…" /> : (
              <div className="space-y-3">
                <div className="text-xs text-slate-500">{schema.database_backend}</div>
                {schema.tables.map((t) => (
                  <details key={t.name} className="rounded-lg border border-slate-200 p-2 dark:border-slate-800">
                    <summary className="cursor-pointer text-sm font-medium">
                      {t.name} <span className="text-xs text-slate-400">· {fmt(t.row_count, 0)} rows</span>
                    </summary>
                    <ul className="mt-2 space-y-0.5 text-xs">
                      {t.columns.map((c) => (
                        <li key={c.name} className="flex justify-between">
                          <span className="font-mono">{c.name}{c.primary_key && " 🔑"}</span>
                          <span className="text-slate-400">{c.data_type}</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                ))}
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
