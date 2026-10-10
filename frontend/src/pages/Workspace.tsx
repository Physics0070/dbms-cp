import { useEffect, useState } from "react";
import { api, fmt, OptimizeResult } from "../api";
import { SqlEditor } from "../components/SqlEditor";
import { PlanFlow, TreeNode, operatorColor } from "../components/PlanFlow";
import { CostBarChart } from "../components/CostChart";
import { Badge, CopyButton, Empty, ErrorNote, Loading, Panel, Segmented, Stat } from "../components/ui";
import { useStore, ResultTab } from "../store";

const EXAMPLES: { label: string; sql: string }[] = [
  {
    label: "3-table join + filter + sort",
    sql: `SELECT c.name, o.total, oi.quantity
FROM customers c
JOIN orders o ON o.customer_id = c.customer_id
JOIN order_items oi ON oi.order_id = o.order_id
WHERE o.status = 'completed' AND c.country = 'India'
ORDER BY o.total DESC`,
  },
  { label: "Selective filter (rare value)", sql: `SELECT * FROM orders WHERE status = 'refunded'` },
  { label: "Common filter", sql: `SELECT * FROM orders WHERE status = 'completed'` },
  { label: "Aggregation", sql: `SELECT status, COUNT(*) AS n FROM orders GROUP BY status ORDER BY n DESC` },
];

export default function Workspace() {
  const { sql, setSql, runOptimize, loading, error, result, benchmark, setBenchmark, tab, setTab } = useStore();
  const [validation, setValidation] = useState<{ valid: boolean; message: string } | null>(null);

  async function validate() {
    try { setValidation(await api.validate(sql)); }
    catch (e: any) { setValidation({ valid: false, message: e.message }); }
  }

  const tabs: { id: ResultTab; label: string; badge?: any }[] = [
    { id: "summary", label: "Summary" },
    { id: "plan", label: "Plan" },
    { id: "candidates", label: "Candidates", badge: result?.optimization.candidates.length },
    { id: "rewrites", label: "Rewrites" },
    { id: "turso", label: "Turso" },
    { id: "index", label: "Index advisor", badge: result?.index_advisor?.recommendations?.length },
    { id: "copilot", label: "Copilot" },
  ];

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-5 p-5">
      {/* Editor ------------------------------------------------------------ */}
      <Panel
        bodyClass="p-3"
        title={
          <div className="flex items-center gap-2">
            <span>Query</span>
            <span className="font-normal text-faint">·</span>
            <span className="font-mono text-2xs font-normal text-faint">read-only SELECT</span>
          </div>
        }
        right={
          <div className="flex items-center gap-2">
            <select
              className="input !py-1 text-xs"
              value=""
              onChange={(e) => { if (e.target.value) { setSql(e.target.value); setValidation(null); } }}
              aria-label="Load an example query"
            >
              <option value="">Examples…</option>
              {EXAMPLES.map((ex) => <option key={ex.label} value={ex.sql}>{ex.label}</option>)}
            </select>
            <CopyButton text={sql} label="Copy" />
          </div>
        }
      >
        <SqlEditor value={sql} onChange={(v) => { setSql(v); setValidation(null); }} onRun={runOptimize} height={212} />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button className="btn btn-primary" onClick={runOptimize} disabled={loading}>
            {loading ? (<><span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/40 border-t-white" /> Optimizing…</>) : "⚡ Optimize"}
          </button>
          <button className="btn btn-ghost" onClick={validate} disabled={loading}>Validate</button>
          <label className="ml-1 flex cursor-pointer items-center gap-2 text-xs text-muted">
            <input type="checkbox" className="accent-[color:var(--accent)]" checked={benchmark}
              onChange={(e) => setBenchmark(e.target.checked)} />
            Benchmark execution
          </label>
          <span className="ml-auto hidden items-center gap-1 text-2xs text-faint sm:flex">
            <span className="kbd">Ctrl</span><span>+</span><span className="kbd">Enter</span><span className="ml-1">to optimize</span>
          </span>
        </div>
        {validation && (
          <div className={`mt-2 rounded-lg px-3 py-2 text-xs ${validation.valid
            ? "bg-[color:var(--ok-soft)] text-ok" : "bg-[color:var(--err-soft)] text-err"}`}>
            {validation.valid ? "✓ " : "✕ "}{validation.message}
          </div>
        )}
        {error && <div className="mt-2"><ErrorNote message={error} /></div>}
      </Panel>

      {/* Results ----------------------------------------------------------- */}
      {loading && !result && (
        <Panel bodyClass="p-0"><Loading label="Discovering schema, computing statistics and costing plans…" /></Panel>
      )}

      {!loading && !result && !error && (
        <Empty icon="⚡" title="Run the optimizer">
          Write a read-only <span className="font-mono">SELECT</span> above and press{" "}
          <span className="font-semibold text-ink">Optimize</span>. You'll get the chosen plan, candidate
          comparison, logical rewrites, a Turso plan comparison, index advice and an AI explanation —
          all from the live database.
        </Empty>
      )}

      {result && (
        <div className="animate-slide-up space-y-4">
          <Segmented tabs={tabs} value={tab} onChange={setTab} />
          {tab === "summary" && <SummaryTab r={result} onJump={setTab} />}
          {tab === "plan" && <PlanTab r={result} />}
          {tab === "candidates" && <CandidatesTab r={result} />}
          {tab === "rewrites" && <RewritesTab r={result} />}
          {tab === "turso" && <TursoTab r={result} />}
          {tab === "index" && <IndexTab r={result} />}
          {tab === "copilot" && <CopilotTab r={result} />}
        </div>
      )}
    </div>
  );
}

const estChip = <Badge tone="accent">estimate</Badge>;
const measuredChip = <Badge tone="ok">measured</Badge>;

/* ------------------------------------------------------------------ Summary */
function SummaryTab({ r, onJump }: { r: OptimizeResult; onJump: (t: ResultTab) => void }) {
  const s = r.summary;
  const overall = r.logical_optimization.overall;
  const b = r.benchmark && !r.benchmark.error ? r.benchmark : null;
  const topIdx = r.index_advisor?.recommendations?.find((x: any) => x.improvement_pct > 0);

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel className="lg:col-span-2" title={<div className="flex items-center gap-2">Estimated {estChip}</div>}>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Plan cost" value={fmt(s.selected_total_cost)} tone="accent" sub="abstract units" />
            <Stat label="Est. rows" value={fmt(s.estimated_cardinality, 0)} />
            <Stat label="Candidates" value={fmt(s.candidate_count, 0)} sub={`${fmt(s.join_orders_considered, 0)} orders`} />
            <Stat label="Optimize time" value={`${fmt(r.optimization_time_ms)}ms`} sub="pipeline" />
          </div>
          <div className="mt-4 rounded-lg border border-line bg-panel-2 p-3">
            <div className="label mb-1">Why this plan won</div>
            <p className="text-sm text-ink">{r.optimization.reason}</p>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <button className="btn btn-ghost text-xs" onClick={() => onJump("plan")}>View plan tree →</button>
            <button className="btn btn-ghost text-xs" onClick={() => onJump("candidates")}>Compare candidates →</button>
            <button className="btn btn-ghost text-xs" onClick={() => onJump("copilot")}>Explain with AI →</button>
          </div>
        </Panel>

        <Panel title={<div className="flex items-center gap-2">Measured {b ? measuredChip : <Badge>unavailable</Badge>}</div>}>
          {b ? (
            <div className="space-y-3">
              <Stat label="Median execution" value={`${fmt(b.median_ms)}ms`} tone="ok"
                sub={`${b.measured_runs} runs · ${b.warmup_runs} warm-up`} />
              <div className="grid grid-cols-3 gap-2 text-center">
                <MiniStat label="min" value={`${fmt(b.min_ms)}ms`} />
                <MiniStat label="avg" value={`${fmt(b.avg_ms)}ms`} />
                <MiniStat label="max" value={`${fmt(b.max_ms)}ms`} />
              </div>
              <div className="text-2xs text-faint">{fmt(b.rows_returned, 0)} rows returned · wall-clock, not comparable to estimated cost.</div>
            </div>
          ) : (
            <p className="text-sm text-muted">Enable <span className="font-medium text-ink">Benchmark execution</span> and re-run to measure real wall-clock time.</p>
          )}
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title={<div className="flex items-center gap-2">Logical rewrite impact {estChip}</div>}>
          <div className="flex items-end gap-4">
            <div>
              <div className="label">before → after</div>
              <div className="mt-1 text-xl font-semibold tabular-nums">
                {fmt(overall.before_cost)} <span className="text-faint">→</span> {fmt(overall.after_cost)}
              </div>
            </div>
            <div className="ml-auto text-right">
              <div className="label">estimated reduction</div>
              <div className={`mt-1 text-2xl font-bold tabular-nums ${overall.improvement_pct > 0 ? "text-ok" : "text-muted"}`}>
                {fmt(overall.improvement_pct)}%
              </div>
            </div>
          </div>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-panel-3">
            <div className="h-full rounded-full bg-ok transition-[width] duration-500"
              style={{ width: `${Math.max(0, Math.min(100, overall.improvement_pct))}%` }} />
          </div>
          <button className="btn btn-ghost mt-3 text-xs" onClick={() => onJump("rewrites")}>See before/after trees →</button>
        </Panel>

        <Panel title="Index advisor">
          {topIdx ? (
            <div className="space-y-2">
              <code className="block rounded-md bg-panel-2 px-2.5 py-2 text-xs text-ink">{topIdx.index_ddl}</code>
              <div className="flex items-center gap-2 text-sm">
                <Badge tone="ok">{fmt(topIdx.improvement_pct)}% cheaper {estChip}</Badge>
                <span className="text-faint">affects {topIdx.affected_operator}</span>
              </div>
              <button className="btn btn-ghost text-xs" onClick={() => onJump("index")}>Review index advice →</button>
            </div>
          ) : (
            <p className="text-sm text-muted">No beneficial hypothetical index was found for this query.</p>
          )}
        </Panel>
      </div>
    </div>
  );
}
function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-line bg-panel-2 py-2">
      <div className="text-2xs uppercase tracking-wide text-faint">{label}</div>
      <div className="mt-0.5 text-sm font-semibold tabular-nums">{value}</div>
    </div>
  );
}

/* --------------------------------------------------------------------- Plan */
function PlanTab({ r }: { r: OptimizeResult }) {
  const plan = r.optimization.selected.plan as unknown as TreeNode;
  const [sel, setSel] = useState<TreeNode | null>(null);
  const node: any = sel || plan;
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
      <Panel title={<div className="flex items-center gap-2">Selected plan <Badge tone="accent">lowest cost</Badge></div>}
        right={<span className="text-2xs text-faint">click a node · +/− to collapse</span>} bodyClass="p-3">
        <PlanFlow root={plan} variant="plan" collapsible onSelect={setSel} selectedId={sel?.id || undefined} height={520} />
        <Legend />
      </Panel>
      <Panel title="Operator">
        <div className="mb-3 flex items-center gap-2">
          <span className="h-3 w-3 rounded-sm" style={{ background: operatorColor(node.operator) }} />
          <span className="text-base font-semibold">{node.operator}</span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <MiniStat label="rows" value={fmt(node.estimated_rows, 0)} />
          <MiniStat label="total cost" value={fmt(node.total_cost)} />
          <MiniStat label="cpu" value={fmt(node.cpu_cost)} />
          <MiniStat label="i/o" value={fmt(node.io_cost)} />
          <MiniStat label="memory" value={fmt(node.memory_cost)} />
          <MiniStat label="self" value={fmt(node.self_total_cost)} />
        </div>
        <p className="mt-3 text-sm text-muted">{node.reasoning}</p>
        {node.meta && Object.keys(node.meta).length > 0 && (
          <details className="mt-3 group">
            <summary className="cursor-pointer select-none text-xs text-faint hover:text-ink">operator metadata</summary>
            <pre className="mt-2 overflow-x-auto rounded-lg bg-panel-2 p-2.5 text-2xs">{JSON.stringify(node.meta, null, 2)}</pre>
          </details>
        )}
      </Panel>
    </div>
  );
}

const LEGEND = [
  ["SeqScan", "Seq scan"], ["IndexScan", "Index scan"], ["HashJoin", "Hash join"],
  ["NestedLoopJoin", "Nested loop"], ["MergeJoin", "Merge join"], ["Sort", "Sort"], ["Aggregate", "Aggregate"],
];
function Legend() {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 px-1 text-2xs text-muted">
      {LEGEND.map(([op, label]) => (
        <span key={op} className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-sm" style={{ background: operatorColor(op) }} />{label}
        </span>
      ))}
      <span className="ml-auto flex items-center gap-1.5">
        <span className="h-1 w-6 rounded-full bg-err" /> higher cost
      </span>
    </div>
  );
}

/* --------------------------------------------------------------- Candidates */
function CandidatesTab({ r }: { r: OptimizeResult }) {
  const opt = r.optimization;
  const rows = [...opt.candidates].sort((a, b) => a.total_cost - b.total_cost);
  const chart = rows.map((c, i) => ({
    id: c.id, label: c.join_order.length ? c.join_order.join("⋈") : `plan ${i + 1}`, cost: c.total_cost,
  }));
  return (
    <div className="space-y-4">
      <Panel title={<div className="flex items-center gap-2">Candidate cost comparison {estChip}</div>}
        right={<span className="text-2xs text-faint">{opt.method} · {fmt(opt.join_orders_considered, 0)} orders</span>}>
        <CostBarChart data={chart} selectedId={opt.selected.id} />
      </Panel>
      <Panel bodyClass="p-0" title="All candidates">
        <div className="overflow-x-auto">
          <table className="data">
            <thead><tr>
              <th>#</th><th>Join order</th><th>Join method</th><th>Operators</th>
              <th className="text-right">Rows</th><th className="text-right">Cost</th><th></th>
            </tr></thead>
            <tbody>
              {rows.map((c, i) => (
                <tr key={c.id} className={c.id === opt.selected.id ? "bg-[color:var(--accent-soft)]" : ""}>
                  <td className="text-faint">{i + 1}</td>
                  <td className="font-mono text-xs">{c.join_order.join(" ⋈ ") || "—"}</td>
                  <td className="text-xs">{[...new Set(c.join_operators)].join(", ") || "—"}</td>
                  <td className="text-2xs text-faint">{[...new Set(c.operators)].join(" · ")}</td>
                  <td className="text-right">{fmt(c.estimated_rows, 0)}</td>
                  <td className="text-right font-semibold">{fmt(c.total_cost)}</td>
                  <td>{c.id === opt.selected.id && <Badge tone="accent">selected</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

/* ----------------------------------------------------------------- Rewrites */
function RewritesTab({ r }: { r: OptimizeResult }) {
  const lo = r.logical_optimization;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-2">
        <Panel title="Original tree" bodyClass="p-3">
          <PlanFlow root={lo.original_tree} variant="ra" height={400} />
        </Panel>
        <Panel title={<div className="flex items-center gap-2">Optimized tree <Badge tone="ok">rewritten</Badge></div>} bodyClass="p-3">
          <PlanFlow root={lo.optimized_tree} variant="ra" height={400} />
        </Panel>
      </div>
      <Panel bodyClass="p-0" title={<div className="flex items-center gap-2">Transformations {estChip}</div>}>
        <table className="data">
          <thead><tr><th>Transformation</th><th className="text-right">Before</th><th className="text-right">After</th><th className="text-right">Δ</th><th>What & why</th></tr></thead>
          <tbody>
            {lo.transformations.map((t) => (
              <tr key={t.name}>
                <td className="font-medium">{t.name}</td>
                <td className="text-right tabular-nums">{fmt(t.before_cost)}</td>
                <td className="text-right tabular-nums">{fmt(t.after_cost)}</td>
                <td className="text-right"><Badge tone={t.improvement_pct > 0 ? "ok" : "neutral"}>{fmt(t.improvement_pct)}%</Badge></td>
                <td className="text-xs text-muted">{t.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}

/* -------------------------------------------------------------------- Turso */
function TursoTab({ r }: { r: OptimizeResult }) {
  const ex = r.explain;
  if (!ex || ex.error) return <Empty title="Unavailable">EXPLAIN comparison unavailable{ex?.error ? `: ${ex.error}` : ""}.</Empty>;
  const c = ex.custom, t = ex.turso;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title={<div className="flex items-center gap-2">Custom optimizer <Badge tone="accent">cost model</Badge></div>}>
          <Rows rows={[
            ["Tables", c.tables.join(", ")], ["Scan methods", c.scan_methods.join(", ") || "—"],
            ["Join methods", c.join_methods.join(", ") || "—"], ["Indexes", c.indexes_used.join(", ") || "none"],
            ["Explicit sort", c.has_sort ? "yes" : "no"],
          ]} />
        </Panel>
        <Panel title={<div className="flex items-center gap-2">Turso / libSQL <Badge>EXPLAIN QUERY PLAN</Badge></div>}>
          <Rows rows={[
            ["Tables", t.tables.join(", ")], ["Indexes", t.indexes_used.join(", ") || "none"],
            ["Temp B-tree", t.uses_temp_btree ? "yes" : "no"],
          ]} />
          <div className="mt-3 label">Raw steps</div>
          <ol className="mt-1 space-y-1">
            {t.steps.map((s: any, i: number) => (
              <li key={i} className="rounded-md bg-panel-2 px-2.5 py-1.5 font-mono text-2xs text-muted">{s.detail}</li>
            ))}
          </ol>
        </Panel>
      </div>
      <Panel title="Differences">
        {ex.differences.length === 0 ? (
          <p className="text-sm text-ok">The plans agree on tables, index usage and sorting.</p>
        ) : (
          <ul className="space-y-1.5 text-sm">
            {ex.differences.map((d: string, i: number) => (
              <li key={i} className="flex gap-2"><span className="text-warn">•</span><span className="text-muted">{d}</span></li>
            ))}
          </ul>
        )}
        <p className="mt-3 text-2xs text-faint">{ex.note}</p>
      </Panel>
    </div>
  );
}
function Rows({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="space-y-1.5 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-4 border-b border-line pb-1.5">
          <dt className="text-muted">{k}</dt><dd className="truncate font-mono text-xs" title={v}>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/* -------------------------------------------------------------------- Index */
function IndexTab({ r }: { r: OptimizeResult }) {
  const adv = r.index_advisor;
  const [created, setCreated] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  if (!adv) return <Empty title="Not run">The index advisor was not run for this query.</Empty>;

  async function create(table: string, columns: string[]) {
    const key = `${table}:${columns.join(",")}`;
    setBusy(key); setErr(null);
    try { const res = await api.createIndex(table, columns); setCreated((c) => ({ ...c, [key]: res.ddl })); setConfirming(null); }
    catch (e: any) { setErr(e.message); }
    finally { setBusy(null); }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-sm text-muted">
        <span>Baseline plan cost <b className="tabular-nums text-ink">{fmt(adv.baseline_cost)}</b></span>
        {estChip}
        <span className="ml-auto text-2xs text-faint">{adv.note}</span>
      </div>
      {err && <ErrorNote message={err} />}
      {adv.recommendations.length === 0 ? (
        <Empty title="No index helps">No beneficial hypothetical index was found for this query.</Empty>
      ) : adv.recommendations.map((x: any) => {
        const key = `${x.table}:${x.columns.join(",")}`;
        const positive = x.improvement_pct > 0;
        return (
          <Panel key={key}>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <code className="rounded-md bg-panel-2 px-2 py-1 text-xs">{x.index_ddl}</code>
                  <Badge>{x.source}</Badge>
                  {x.affected_operator !== "none" && <Badge tone="accent">{x.affected_operator}</Badge>}
                </div>
                <p className="mt-2 max-w-2xl text-sm text-muted">{x.reason}</p>
                <p className="mt-1 text-2xs text-faint">Overhead ≈ {fmt(x.estimated_overhead.index_entries, 0)} entries. {x.estimated_overhead.note}</p>
              </div>
              <div className="text-right">
                <div className="label">current → hypothetical {estChip}</div>
                <div className="mt-1 tabular-nums"><b>{fmt(x.current_cost)}</b> → <b>{fmt(x.hypothetical_cost)}</b></div>
                <div className="mt-1"><Badge tone={positive ? "ok" : "neutral"}>{fmt(x.improvement_pct)}% {positive ? "cheaper" : "no gain"}</Badge></div>
                {positive && (
                  <div className="mt-2">
                    {created[key] ? <Badge tone="ok">created ✓</Badge>
                      : confirming === key ? (
                        <div className="flex items-center gap-1.5">
                          <button className="btn btn-primary !py-1 text-2xs" disabled={busy === key} onClick={() => create(x.table, x.columns)}>
                            {busy === key ? "Creating…" : "Confirm"}
                          </button>
                          <button className="btn btn-ghost !py-1 text-2xs" onClick={() => setConfirming(null)}>Cancel</button>
                        </div>
                      ) : (
                        <button className="btn btn-ghost !py-1 text-2xs" onClick={() => setConfirming(key)}>Create index…</button>
                      )}
                  </div>
                )}
              </div>
            </div>
          </Panel>
        );
      })}
    </div>
  );
}

/* ------------------------------------------------------------------ Copilot */
function CopilotTab({ r }: { r: OptimizeResult }) {
  const [answer, setAnswer] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function ask(question?: string) {
    setLoading(true); setErr(null);
    try { setAnswer(await api.copilot(r.sql, question)); }
    catch (e: any) { setErr(e.message); }
    finally { setLoading(false); }
  }
  useEffect(() => { ask(); /* auto-explain on open */ }, [r.sql]); // eslint-disable-line

  return (
    <div className="space-y-3">
      <Panel>
        <div className="flex flex-wrap items-center gap-2">
          <button className="btn btn-ghost text-sm" onClick={() => ask()} disabled={loading}>↻ Re-explain</button>
          <input className="input min-w-[16rem] flex-1 text-sm" placeholder="Ask about this plan…"
            value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && q && ask(q)} />
          <button className="btn btn-primary text-sm" onClick={() => q && ask(q)} disabled={loading || !q}>Ask</button>
        </div>
        <p className="mt-2 text-2xs text-faint">Grounded only in this query's optimizer output — the assistant won't invent metrics.</p>
      </Panel>
      {loading && <Panel><Loading label="Consulting the copilot…" /></Panel>}
      {err && <ErrorNote message={err} />}
      {answer && !loading && (
        <Panel title={<div className="flex items-center gap-2">Explanation <Badge tone={answer.source === "openai" ? "ok" : "neutral"}>{answer.source}{answer.model ? ` · ${answer.model}` : ""}</Badge></div>}>
          {answer.warning && <div className="mb-3 rounded-md bg-[color:var(--warn-soft)] px-2.5 py-1.5 text-xs text-warn">{answer.warning}</div>}
          <Markdown md={answer.explanation} />
        </Panel>
      )}
    </div>
  );
}

function Markdown({ md }: { md: string }) {
  return (
    <div className="space-y-0.5 text-sm leading-relaxed">
      {md.split("\n").map((line, i) => {
        if (line.startsWith("### ")) return <h4 key={i} className="mt-4 label text-accent">{line.slice(4)}</h4>;
        if (line.startsWith("- ")) return <li key={i} className="ml-5 list-disc text-muted">{inline(line.slice(2))}</li>;
        if (!line.trim()) return <div key={i} className="h-1.5" />;
        return <p key={i} className="text-ink">{inline(line)}</p>;
      })}
    </div>
  );
}
function inline(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
    p.startsWith("**") && p.endsWith("**") ? <b key={i} className="text-ink">{p.slice(2, -2)}</b> : <span key={i}>{p}</span>);
}
