import { ReactNode, useEffect, useMemo, useState } from "react";
import { api, fmt, OptimizeResult, OptimizedQuery, SchemaResponse } from "../api";
import { SqlEditor, SqlView } from "../components/SqlEditor";
import { diffLines } from "../lib/diff";
import { PlanFlow, TreeNode, operatorColor, planToText } from "../components/PlanFlow";
import { CostBarChart } from "../components/CostChart";
import { PlanDetails } from "../components/PlanDetails";
import { PlanDiff } from "../components/PlanDiff";
import { Badge, CopyButton, Empty, ErrorNote, Loading, Verdict } from "../components/ui";
import { Onboarding } from "../components/Onboarding";
import { useStore, ResultTab } from "../store";

/* ---------------------------------------------------------------- primitives
   Local to the workspace: hairline sections with chapter numbers, and figures set in mono. */
function Sec({
  n, title, right, children, className = "", bodyClass = "p-4", tone = "solid",
}: {
  n?: string; title?: ReactNode; right?: ReactNode; children: ReactNode;
  className?: string; bodyClass?: string; tone?: "solid" | "dashed";
}) {
  return (
    <section className={`border bg-panel ${tone === "dashed" ? "border-dashed border-line-2" : "border-line"} ${className}`}>
      {title && (
        <header className="flex min-h-[36px] flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-line px-4 py-1.5">
          <h3 className="flex items-baseline gap-2 font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-muted">
            {n && <span className="text-accent">{n}</span>}
            {title}
          </h3>
          {right}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

function Fig({ label, value, sub, tone = "default", big = false }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: "default" | "accent" | "ok"; big?: boolean;
}) {
  const cls = tone === "accent" ? "text-accent" : tone === "ok" ? "text-ok" : "text-ink";
  return (
    <div className="border-l border-line-2 pl-3">
      <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">{label}</div>
      <div className={`mt-1 font-mono font-medium tabular-nums ${big ? "text-3xl" : "text-xl"} ${cls}`}>{value}</div>
      {sub && <div className="mt-0.5 font-mono text-[11px] text-faint">{sub}</div>}
    </div>
  );
}

const estChip = <Badge tone="accent">estimate</Badge>;
const measuredChip = <Badge tone="ok">measured</Badge>;

/* ------------------------------------------------------------------ verdict */
interface Verdict { headline: string; tone: "ok" | "warn" | "neutral"; detail: string }

/** One honest sentence, derived only from fields the backend returned. */
function verdictOf(r: OptimizeResult): Verdict {
  const o = r.optimized_query;
  const bm = o?.benchmark && !o.benchmark.error ? o.benchmark : null;
  if (!o) return { headline: "Plan costed.", tone: "neutral", detail: r.optimization.reason };
  if (o.status === "rewritten") {
    if (bm?.verdict === "faster")
      return { headline: "The rewrite measured faster.", tone: "ok",
        detail: "Its timings sit consistently below the original's on this database, and it returns the same rows." };
    if (bm?.verdict === "slower")
      return { headline: "Keep your original query.", tone: "warn",
        detail: `The cost model estimated a ${fmt(o.estimated.improvement_pct)}% gain, but the rewrite ran slower here. The engine's own planner already chose well.` };
    if (bm)
      return { headline: "No measurable difference.", tone: "neutral",
        detail: `The estimate says ${fmt(o.estimated.improvement_pct)}%, but the measured ranges overlap, so no speedup can be claimed.` };
    return { headline: "A rewrite exists, not yet measured.", tone: "neutral",
      detail: `The cost model estimates ${fmt(o.estimated.improvement_pct)}%. That is a prediction. Turn on benchmarking and re-run to time both.` };
  }
  if (o.status === "no_change") return { headline: "Already optimal.", tone: "neutral", detail: o.reasons[0] ?? "The cost model found no cheaper join order." };
  if (o.status === "unsupported") return { headline: "No rewrite offered.", tone: "neutral", detail: o.reasons[0] ?? "This query shape is not rewritten." };
  if (o.status === "rejected" || o.status === "unverified")
    return { headline: "Rewrite withheld.", tone: "warn", detail: o.reasons[0] ?? "The rewrite could not be verified as equivalent." };
  return { headline: "Rewrite unavailable.", tone: "neutral", detail: o.reasons?.[0] ?? "The optimized query could not be generated." };
}

/* ---------------------------------------------------------------- the page */
const TABS: { id: ResultTab; label: string }[] = [
  { id: "summary", label: "Overview" },
  { id: "optimized", label: "Optimized query" },
  { id: "plan", label: "Plan" },
  { id: "candidates", label: "Candidates" },
  { id: "rewrites", label: "Rewrites" },
  { id: "engine", label: "SQLite plan" },
  { id: "index", label: "Index advisor" },
  { id: "copilot", label: "Copilot" },
];

export default function Workspace() {
  const { sql, setSql, examples, runOptimize, loading, error, result, benchmark, setBenchmark, tab, setTab } = useStore();
  const [validation, setValidation] = useState<{ valid: boolean; message: string } | null>(null);

  async function validate() {
    try { setValidation(await api.validate(sql)); }
    catch (e: any) { setValidation({ valid: false, message: e.message }); }
  }

  const badge = (id: ResultTab): string | number | undefined => {
    if (!result) return undefined;
    if (id === "optimized") return optBadge(result.optimized_query);
    if (id === "candidates") return result.optimization.candidates.length;
    if (id === "index") return result.index_advisor?.recommendations?.length;
    return undefined;
  };

  return (
    <div className="grid min-h-full grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(380px,2fr)_minmax(0,3fr)]">
      {/* LEFT: query + context. Sticky on desktop so the SQL stays in view while reading evidence. */}
      <aside className="min-w-0 border-line lg:sticky lg:top-0 lg:max-h-[calc(100dvh-3.5rem)] lg:self-start lg:overflow-y-auto lg:border-r">
        <div className="space-y-5 p-4 sm:p-5">
          <section aria-labelledby="ws-query">
            <div className="mb-2 flex items-baseline justify-between gap-2">
              <h2 id="ws-query" className="flex items-baseline gap-2 font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-muted">
                <span className="text-accent">01</span> Query
              </h2>
              <span className="font-mono text-[11px] text-faint">read-only SELECT</span>
            </div>
            <SqlEditor value={sql} onChange={(v) => { setSql(v); setValidation(null); }} onRun={runOptimize} height={236} />
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button className="btn btn-primary" onClick={runOptimize} disabled={loading || !sql.trim()}>
                {loading ? (<><span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-black/30 border-t-black" /> Optimizing…</>) : "Optimize"}
              </button>
              <button className="btn btn-ghost" onClick={validate} disabled={loading}>Validate</button>
              <CopyButton text={sql} label="Copy" />
              <label className="ml-auto flex cursor-pointer items-center gap-2 text-xs text-muted">
                <input type="checkbox" className="accent-[color:var(--accent)]" checked={benchmark}
                  onChange={(e) => setBenchmark(e.target.checked)} />
                Benchmark execution
              </label>
            </div>
            <p className="mt-2 hidden items-center gap-1 font-mono text-[11px] text-faint sm:flex">
              <span className="kbd">Ctrl</span>+<span className="kbd">Enter</span> optimize · <span className="kbd">Ctrl</span>+<span className="kbd">Shift</span>+<span className="kbd">F</span> format
            </p>
            {validation && (
              <div className={`mt-2 border-l-2 px-3 py-1.5 text-xs ${validation.valid
                ? "border-ok bg-[color:var(--ok-soft)] text-ok" : "border-err bg-[color:var(--err-soft)] text-err"}`}>
                {validation.valid ? "✓ " : "✕ "}{validation.message}
              </div>
            )}
            {error && <div className="mt-2"><ErrorNote message={error} /></div>}

            <div className="mt-4">
              <div className="mb-1.5 font-mono text-[10px] uppercase tracking-[0.14em] text-faint">
                {examples.length ? "Examples generated from your schema" : "No examples for this database"}
              </div>
              <div className="flex flex-wrap gap-1.5" role="group" aria-label="Example queries">
                {examples.map((ex) => (
                  <button key={ex.label} type="button" title={ex.sql}
                    className="max-w-full truncate border border-line bg-panel-2 px-2 py-1 font-mono text-[11px] text-muted hover:border-line-2 hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--ring)]"
                    onClick={() => { setSql(ex.sql); setValidation(null); }}>
                    {ex.label}
                  </button>
                ))}
              </div>
            </div>
          </section>

          <ContextPane sql={sql} />
        </div>
      </aside>

      {/* RIGHT: verdict first, then the evidence, then detail. */}
      <div className="min-w-0 p-4 sm:p-5">
        {loading && !result && <Sec bodyClass="p-0"><Loading label="Discovering schema, computing statistics and costing plans…" /></Sec>}
        {!loading && !result && !error && <Onboarding />}

        {result && (
          <div className="animate-slide-up space-y-5">
            <VerdictBlock r={result} onJump={setTab} />

            <div>
              <div role="tablist" aria-label="Analysis detail"
                className="flex items-center gap-0 overflow-x-auto border-b border-line">
                <span className="mr-3 shrink-0 font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-muted"><span className="text-accent">05</span> Detail</span>
                {TABS.map((t) => {
                  const b = badge(t.id);
                  return (
                    <button key={t.id} role="tab" id={`tab-${t.id}`} aria-selected={tab === t.id} aria-controls="ws-panel"
                      onClick={() => setTab(t.id)}
                      className={`-mb-px shrink-0 whitespace-nowrap border-b-2 px-3 py-2 text-sm transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--ring)]
                        ${tab === t.id ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink"}`}>
                      {t.label}
                      {b != null && <span className="ml-1.5 font-mono text-[11px] tabular-nums text-faint">{b}</span>}
                    </button>
                  );
                })}
              </div>
              <div id="ws-panel" role="tabpanel" aria-labelledby={`tab-${tab}`} className="pt-4">
                {tab === "summary" && <OverviewTab r={result} onJump={setTab} />}
                {tab === "optimized" && <OptimizedTab r={result} />}
                {tab === "plan" && <PlanTab r={result} />}
                {tab === "candidates" && <CandidatesTab r={result} />}
                {tab === "rewrites" && <RewritesTab r={result} />}
                {tab === "engine" && <EnginePlanTab r={result} />}
                {tab === "index" && <IndexTab r={result} />}
                {tab === "copilot" && <CopilotTab r={result} />}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ context */
function ContextPane({ sql }: { sql: string }) {
  const [db, setDb] = useState<any | null>(null);
  const [schema, setSchema] = useState<SchemaResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [filter, setFilter] = useState("");
  useEffect(() => {
    api.database().then(setDb).catch(() => {});
    api.schema().then(setSchema).catch(() => setFailed(true));
  }, []);

  // A table counts as "in this query" only when its name appears as a whole word in the SQL text.
  const used = useMemo(() => {
    const hay = sql.toLowerCase();
    const s = new Set<string>();
    schema?.tables.forEach((t) => {
      const esc = t.name.toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      if (new RegExp(`(^|[^a-z0-9_])${esc}($|[^a-z0-9_])`).test(hay)) s.add(t.name);
    });
    return s;
  }, [sql, schema]);

  const tables = (schema?.tables ?? [])
    .filter((t) => !filter || t.name.toLowerCase().includes(filter.toLowerCase()))
    .sort((a, b) => Number(used.has(b.name)) - Number(used.has(a.name)) || a.name.localeCompare(b.name));
  const fkCols = (t: SchemaResponse["tables"][number]) => new Set(t.foreign_keys.flatMap((f) => f.columns));

  return (
    <section aria-labelledby="ws-context">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h2 id="ws-context" className="flex items-baseline gap-2 font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-muted">
          <span className="text-accent">02</span> Context
        </h2>
        {db?.connected && <span className="truncate font-mono text-[11px] text-faint" title={db.label}>{db.engine} · {db.name}</span>}
      </div>
      {failed && <p className="text-xs text-muted">The schema could not be read.</p>}
      {!schema && !failed && <Loading label="Reading schema…" />}
      {schema && (
        <div className="border border-line bg-panel">
          <div className="flex items-center gap-2 border-b border-line px-3 py-1.5">
            <span className="font-mono text-[11px] text-faint">{used.size} of {schema.tables.length} tables in query</span>
            {schema.tables.length > 8 && (
              <input className="input ml-auto !py-0.5 !text-xs" type="search" placeholder="Filter tables…" aria-label="Filter tables"
                value={filter} onChange={(e) => setFilter(e.target.value)} />
            )}
          </div>
          <ul className="max-h-[260px] divide-y divide-line overflow-y-auto">
            {tables.map((t) => {
              const fks = fkCols(t);
              return (
                <li key={t.name}>
                  <details className="group">
                    <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-1.5 text-xs hover:bg-panel-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--ring)]">
                      <span className={`h-1.5 w-1.5 shrink-0 ${used.has(t.name) ? "bg-accent" : "border border-line-2"}`} aria-hidden="true" />
                      <span className={`font-mono ${used.has(t.name) ? "text-ink" : "text-muted"}`}>{t.name}</span>
                      {used.has(t.name) && <span className="font-mono text-[10px] uppercase tracking-wider text-accent">in query</span>}
                      <span className="ml-auto font-mono text-[11px] tabular-nums text-faint">
                        {t.row_count != null ? `${fmt(t.row_count, 0)} rows` : "rows n/a"} · {t.columns.length} col · {t.indexes.length} idx
                      </span>
                    </summary>
                    <ul className="border-t border-line bg-panel-2 px-3 py-1.5 font-mono text-[11px] text-muted">
                      {t.columns.map((c) => (
                        <li key={c.name} className="flex items-center gap-2 py-0.5">
                          <span className="text-ink">{c.name}</span>
                          <span className="text-faint">{c.data_type || "—"}</span>
                          {c.primary_key && <span className="text-accent">PK</span>}
                          {fks.has(c.name) && <span className="text-muted">FK</span>}
                        </li>
                      ))}
                      {t.indexes.length > 0 && (
                        <li className="mt-1 border-t border-line pt-1 text-faint">
                          indexes: {t.indexes.map((i) => `${i.name}(${i.columns.join(", ")})`).join(" · ")}
                        </li>
                      )}
                    </ul>
                  </details>
                </li>
              );
            })}
            {tables.length === 0 && <li className="px-3 py-3 text-xs text-muted">No tables match.</li>}
          </ul>
        </div>
      )}
    </section>
  );
}

/* --------------------------------------------------- verdict + the evidence */
function VerdictBlock({ r, onJump }: { r: OptimizeResult; onJump: (t: ResultTab) => void }) {
  const { setSql, setTab } = useStore();
  const s = r.summary;
  const o = r.optimized_query;
  const v = verdictOf(r);
  const b = r.benchmark && !r.benchmark.error ? r.benchmark : null;
  const bm = o?.benchmark && !o.benchmark.error ? o.benchmark : null;
  const eq = o?.status === "rewritten" ? o.equivalence : null;

  return (
    <div className="space-y-5">
      <section aria-labelledby="ws-verdict">
        <h2 id="ws-verdict" className="sr-only">Verdict</h2>
        <Verdict tone={v.tone} label="03 · Verdict" headline={v.headline}>
          <p>{v.detail}</p>
          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 font-mono text-[11px]">
            {eq ? (
              <span className="inline-flex items-center gap-1.5 text-ok" title={eq.note}>
                <span aria-hidden="true">✓</span> verified equivalent · {eq.original_rows} row{eq.original_rows === 1 ? "" : "s"}, same columns
              </span>
            ) : (
              <span className="text-faint">equivalence: no rewrite to verify</span>
            )}
            {bm && bm.verdict !== "indistinguishable" && (
              <span className="tabular-nums text-muted">median {fmt(bm.original.median_ms)}ms → {fmt(bm.optimized.median_ms)}ms ({fmt(Math.abs(bm.median_change_pct))}% {bm.median_change_pct >= 0 ? "lower" : "higher"})</span>
            )}
            {o?.status === "rewritten" && o.sql && (
              <button className={`btn !py-1 text-xs ${bm?.verdict === "slower" ? "btn-ghost" : "btn-primary"}`}
                onClick={() => { setSql(o.sql!); setTab("summary"); }} title="Load the optimized SQL into the editor">
                Use rewritten query
              </button>
            )}
          </div>
        </Verdict>
      </section>

      <section aria-labelledby="ws-evidence">
        <div className="mb-3 flex items-baseline gap-2 font-mono text-[11px] font-medium uppercase tracking-[0.14em] text-muted">
          <span className="text-accent">04</span><span id="ws-evidence">Evidence</span>
          <span className="ml-2 normal-case tracking-normal text-faint">predicted and measured are never mixed</span>
        </div>
        <div className="grid gap-4 xl:grid-cols-2">
          {/* Estimated: dashed frame = a prediction from the cost model. */}
          <Sec tone="dashed" title="Estimated" right={<span className="font-mono text-[11px] text-faint">cost model · abstract units</span>}>
            <div className="grid grid-cols-2 gap-4">
              <Fig label="Plan cost" value={fmt(s.selected_total_cost)} tone="accent" big />
              <Fig label="Est. rows" value={fmt(s.estimated_cardinality, 0)} big />
              <Fig label="Candidates" value={fmt(s.candidate_count, 0)} sub={`${fmt(s.join_orders_considered, 0)} join orders`} />
              <Fig label="Optimize time" value={`${fmt(r.optimization_time_ms)}ms`} sub="pipeline, not query time" />
            </div>
            <div className="mt-4 border-t border-line pt-3">
              <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">Why this plan won</div>
              <p className="mt-1 text-sm leading-relaxed text-ink">{r.optimization.reason}</p>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <button className="btn btn-ghost !py-1 text-xs" onClick={() => onJump("plan")}>Plan tree →</button>
              <button className="btn btn-ghost !py-1 text-xs" onClick={() => onJump("candidates")}>Candidates →</button>
              <button className="btn btn-ghost !py-1 text-xs" onClick={() => onJump("copilot")}>Explain →</button>
            </div>
          </Sec>

          {/* Measured: solid frame = wall-clock on this database. */}
          <Sec title={b ? "Measured" : <>Measured <Badge>unavailable</Badge></>} right={<span className="font-mono text-[11px] text-faint">wall-clock · this database</span>}>
            {b ? (
              <>
                <Fig label="Median execution" value={`${fmt(b.median_ms)}ms`} tone="ok" big
                  sub={`${b.measured_runs} runs · ${b.warmup_runs} warm-up`} />
                <div className="mt-4 grid grid-cols-3 gap-4">
                  <Fig label="min" value={`${fmt(b.min_ms)}ms`} />
                  <Fig label="avg" value={`${fmt(b.avg_ms)}ms`} />
                  <Fig label="max" value={`${fmt(b.max_ms)}ms`} />
                </div>
                <p className="mt-4 border-t border-line pt-3 font-mono text-[11px] leading-relaxed text-faint">
                  {fmt(b.rows_returned, 0)} rows returned. One isolated timing proves nothing; the spread above is the point. Not comparable to estimated cost.
                </p>
              </>
            ) : (
              <p className="text-sm text-muted">Turn on <span className="font-medium text-ink">Benchmark execution</span> and re-run to measure real wall-clock time.</p>
            )}
          </Sec>
        </div>
      </section>
    </div>
  );
}

/* ----------------------------------------------------------------- Overview */
function OverviewTab({ r, onJump }: { r: OptimizeResult; onJump: (t: ResultTab) => void }) {
  const overall = r.logical_optimization.overall;
  const topIdx = r.index_advisor?.recommendations?.find((x: any) => x.improvement_pct > 0);

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Sec title={<>Logical rewrite impact {estChip}</>}>
        <div className="flex items-end gap-4">
          <Fig label="before → after" value={<>{fmt(overall.before_cost)} <span className="text-faint">→</span> {fmt(overall.after_cost)}</>} />
          <div className="ml-auto text-right">
            <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-faint">estimated reduction</div>
            <div className={`mt-1 font-mono text-2xl tabular-nums ${overall.improvement_pct > 0 ? "text-ink" : "text-muted"}`}>
              {fmt(overall.improvement_pct)}%
            </div>
          </div>
        </div>
        <div className="mt-3 h-1 bg-panel-3" role="img" aria-label={`Estimated reduction ${fmt(overall.improvement_pct)} percent`}>
          <div className="h-full bg-accent transition-[width] duration-500"
            style={{ width: `${Math.max(0, Math.min(100, overall.improvement_pct))}%` }} />
        </div>
        <p className="mt-3 font-mono text-[11px] text-faint">Baseline: {overall.baseline}</p>
        <p className="mt-0.5 font-mono text-[11px] text-faint">
          For reference, against a plan with no pushdown at all ({fmt(overall.naive_cost)}): {fmt(overall.naive_improvement_pct)}% — {overall.naive_baseline}
        </p>
        <button className="btn btn-ghost mt-3 !py-1 text-xs" onClick={() => onJump("rewrites")}>Before/after trees →</button>
      </Sec>

      <Sec title="Index advisor">
        {topIdx ? (
          <div className="space-y-2">
            <code className="block overflow-x-auto border border-line bg-panel-2 px-2.5 py-2 font-mono text-xs text-ink">{topIdx.index_ddl}</code>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Badge tone="accent">{fmt(topIdx.improvement_pct)}% cheaper (estimate)</Badge>
              <span className="font-mono text-[11px] text-faint">affects {topIdx.affected_operator}</span>
            </div>
            <button className="btn btn-ghost !py-1 text-xs" onClick={() => onJump("index")}>Review index advice →</button>
          </div>
        ) : (
          <p className="text-sm text-muted">No beneficial hypothetical index was found for this query.</p>
        )}
      </Sec>
    </div>
  );
}

/* ---------------------------------------------------------- Optimized query */
function optBadge(o?: OptimizedQuery) {
  if (!o) return undefined;
  return o.status === "rewritten" ? "✓" : o.status === "no_change" ? "=" : "!";
}

function OptimizedTab({ r }: { r: OptimizeResult }) {
  const o = r.optimized_query;
  const { setSql, setTab } = useStore();
  const [showEngine, setShowEngine] = useState(false);
  const [markChanges, setMarkChanges] = useState(true);

  if (!o || o.status === "error") {
    return <Empty title="Unavailable">{o?.reasons?.join(" ") || "The optimized query could not be generated."}</Empty>;
  }

  if (o.status === "no_change" || o.status === "unsupported") {
    const already = o.status === "no_change";
    return (
      <Sec title={<div className="flex items-center gap-2">
        {already ? "Already optimal" : "Not rewritten"}
        <Badge tone={already ? "ok" : "warn"}>{already ? "no change needed" : "unsupported"}</Badge>
      </div>}>
        <div className="space-y-3">
          <ul className="space-y-1.5 text-sm">
            {o.reasons.map((x, i) => (
              <li key={i} className="flex gap-2"><span className={already ? "text-ok" : "text-warn"}>•</span><span className="text-muted">{x}</span></li>
            ))}
          </ul>
          {already && r.index_advisor?.recommendations?.some((x: any) => x.improvement_pct > 0) && (
            <button className="btn btn-ghost text-xs" onClick={() => setTab("index")}>See index suggestions →</button>
          )}
          <div>
            <div className="label mb-1.5">Your query</div>
            <SqlView sql={o.original_sql} maxHeight={220} />
          </div>
        </div>
      </Sec>
    );
  }

  if (o.status === "rejected" || o.status === "unverified") {
    return (
      <Sec title={<div className="flex items-center gap-2">Rewrite withheld <Badge tone="err">{o.status}</Badge></div>}>
        <p className="text-sm text-muted">{o.reasons.join(" ")}</p>
        <p className="mt-2 text-2xs text-faint">A rewrite is only shown as an optimization after the database confirms it returns the same rows.</p>
        {o.rejected_sql && (
          <details className="mt-3">
            <summary className="cursor-pointer text-xs text-faint hover:text-ink">candidate SQL (not equivalent / not verified)</summary>
            <div className="mt-2"><SqlView sql={o.rejected_sql} maxHeight={240} /></div>
          </details>
        )}
      </Sec>
    );
  }

  // status === "rewritten" (verified equivalent)
  const eq = o.equivalence!;
  const diff = diffLines(o.original_pretty, o.sql!);
  const bm = o.benchmark && !o.benchmark.error ? o.benchmark : null;
  const verdictTone = bm?.verdict === "faster" ? "ok" : bm?.verdict === "slower" ? "warn" : "neutral";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 border border-line bg-panel px-4 py-3">
        <Badge tone="ok">verified equivalent</Badge>
        <span className="text-sm text-ink">
          {eq.original_rows} row{eq.original_rows === 1 ? "" : "s"} from both queries — same columns, same rows.
        </span>
        <span className="text-2xs text-faint">{eq.note}</span>
        <button className={`btn ml-auto !py-1 text-xs ${bm?.verdict === "slower" ? "btn-ghost" : "btn-primary"}`}
          onClick={() => { setSql(o.sql!); setTab("summary"); }} title="Load the optimized SQL into the editor">
          Use this query
        </button>
      </div>

      {/* The measurement outranks the estimate: say what actually happened. */}
      <div className={`border px-4 py-3 text-sm ${
        bm?.verdict === "faster" ? "border-[color:var(--ok)] bg-[color:var(--ok-soft)]"
        : bm?.verdict === "slower" ? "border-[color:var(--warn)] bg-[color:var(--warn-soft)]"
        : "border-line bg-panel"}`}>
        {!bm && (<span className="text-muted">
          <b className="text-ink">Not measured.</b> The cost model estimates a gain of {fmt(o.estimated.improvement_pct)}%, but that is an
          estimate. Turn on <span className="font-medium text-ink">Benchmark execution</span> and re-run to time both queries.</span>)}
        {bm?.verdict === "faster" && (<span><b className="text-ok">Measured faster.</b> <span className="text-muted">
          The optimized query's timings are consistently below the original's on this database.</span></span>)}
        {bm?.verdict === "slower" && (<span><b className="text-warn">Measured slower — keep your original query.</b> <span className="text-muted">
          The cost model predicted a gain of {fmt(o.estimated.improvement_pct)}%, but on this database the rewrite ran slower. SQLite's
          planner already chooses a good join order on its own, and pinning ours overrides it.</span></span>)}
        {bm?.verdict === "indistinguishable" && (<span><b className="text-ink">No measurable difference.</b> <span className="text-muted">
          The cost model predicted {fmt(o.estimated.improvement_pct)}%, but the timings overlap, so no speedup can be claimed.</span></span>)}
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Sec title={<div className="flex items-center gap-2">Original <span className="text-2xs font-normal text-faint">reformatted</span></div>}
          right={<div className="flex items-center gap-2">
            <label className="flex cursor-pointer items-center gap-1.5 text-2xs text-muted">
              <input type="checkbox" className="accent-[color:var(--accent)]" checked={markChanges}
                onChange={(e) => setMarkChanges(e.target.checked)} />
              Highlight changes
            </label>
            <CopyButton text={o.original_sql} />
          </div>} bodyClass="p-3">
          <SqlView sql={o.original_pretty} marks={markChanges ? diff.removed : undefined} markTone="del" />
        </Sec>
        <Sec title={<div className="flex items-center gap-2">Optimized <Badge tone="ok">rewritten</Badge></div>}
          right={<CopyButton text={o.sql!} />} bodyClass="p-3">
          <SqlView sql={o.sql!} marks={markChanges ? diff.added : undefined} markTone="add" />
        </Sec>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Sec title={<div className="flex items-center gap-2">Estimated {estChip}</div>}>
          <div className="flex items-end gap-4">
            <div>
              <div className="label">cost before → after</div>
              <div className="mt-1 text-xl font-semibold tabular-nums">
                {fmt(o.estimated.before_cost)} <span className="text-faint">→</span> {fmt(o.estimated.after_cost)}
              </div>
            </div>
            <div className="ml-auto text-right">
              <div className="label">estimated reduction</div>
              <div className={`mt-1 text-2xl font-bold tabular-nums ${o.estimated.improvement_pct > 0 ? "text-ok" : "text-muted"}`}>
                {fmt(o.estimated.improvement_pct)}%
              </div>
            </div>
          </div>
          <p className="mt-3 text-2xs text-faint">Baseline: {o.estimated.baseline}</p>
          <p className="mt-0.5 text-2xs text-faint">
            For reference, against a plan with no pushdown ({fmt(o.estimated.naive_cost)}): {fmt(o.estimated.naive_improvement_pct)}%. {o.estimated.naive_baseline}
          </p>
          <p className="mt-1 text-2xs text-faint">{o.estimated.note}</p>
        </Sec>

        <Sec title={<div className="flex items-center gap-2">Measured {bm ? measuredChip : <Badge>unavailable</Badge>}</div>}>
          {bm ? (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <Fig label="Original median" value={`${fmt(bm.original.median_ms)}ms`} sub={`${fmt(bm.original.min_ms)}–${fmt(bm.original.max_ms)}ms`} />
                <Fig label="Optimized median" value={`${fmt(bm.optimized.median_ms)}ms`} sub={`${fmt(bm.optimized.min_ms)}–${fmt(bm.optimized.max_ms)}ms`}
                  tone={bm.verdict === "faster" ? "ok" : "default"} />
              </div>
              <div className="flex items-center gap-2 text-sm">
                <Badge tone={verdictTone as any}>{bm.verdict === "indistinguishable" ? "no measurable difference" : bm.verdict}</Badge>
                {bm.verdict !== "indistinguishable" && (
                  <span className="tabular-nums text-muted">{fmt(Math.abs(bm.median_change_pct))}% {bm.median_change_pct >= 0 ? "lower" : "higher"} median</span>
                )}
              </div>
              <p className="text-2xs text-faint">{bm.note}</p>
            </div>
          ) : (
            <p className="text-sm text-muted">Turn on <span className="font-medium text-ink">Benchmark execution</span> and re-run to time both queries on the same data.</p>
          )}
        </Sec>
      </div>

      <Sec title="What changed" bodyClass="p-0">
        <ul className="divide-y divide-line">
          {o.changes.map((c) => (
            <li key={c.name} className="grid gap-1 px-4 py-3 text-sm md:grid-cols-[170px_1fr]">
              <div className="font-semibold">{c.name}</div>
              <div>
                <p className="text-ink">{c.what}</p>
                <p className="mt-1 text-muted"><span className="text-faint">Why: </span>{c.why}</p>
                <p className="mt-0.5 text-2xs text-faint">Trade-off: {c.tradeoff}</p>
              </div>
            </li>
          ))}
        </ul>
      </Sec>

      {o.engine_plan && (
        <div>
          <button className="btn btn-subtle !px-0 text-xs" onClick={() => setShowEngine((v) => !v)}>
            {showEngine ? "▾" : "▸"} SQLite query plan for the optimized SQL
          </button>
          {showEngine && (
            <ol className="mt-2 space-y-1">
              {o.engine_plan.map((d, i) => (
                <li key={i} className="bg-panel-2 px-2.5 py-1.5 font-mono text-2xs text-muted">{d}</li>
              ))}
            </ol>
          )}
        </div>
      )}
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
      <Sec title={<div className="flex items-center gap-2">Selected plan <Badge tone="accent">lowest cost</Badge></div>}
        right={<div className="flex items-center gap-2"><span className="hidden text-2xs text-faint sm:inline">click or press Enter on a node · +/− to collapse</span><CopyButton text={planToText(plan)} label="Copy plan" /></div>} bodyClass="p-3">
        <PlanFlow root={plan} variant="plan" edgeTone="ok" collapsible searchable onSelect={setSel} selectedId={sel?.id || undefined} height={520}
          provenance="candidate plan (this platform, estimated)" />
        <Legend />
      </Sec>
      <Sec title="Operator">
        <PlanDetails node={node} sql={r.sql} />
      </Sec>
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
        <span className="h-1 w-6 bg-accent" /> self cost vs. costliest operator · tier also shown as border style and ▲ HIGH / ▲ MED / LOW
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
      <Sec title={<div className="flex items-center gap-2">Candidate cost comparison {estChip}</div>}
        right={<span className="text-2xs text-faint">{opt.method} · {fmt(opt.join_orders_considered, 0)} orders</span>}>
        <CostBarChart data={chart} selectedId={opt.selected.id} />
      </Sec>
      <Sec title={<div className="flex items-center gap-2">Compare two candidate plans {estChip}</div>} bodyClass="p-3">
        <PlanDiff candidates={opt.candidates} selectedId={opt.selected.id} />
      </Sec>
      <Sec bodyClass="p-0" title="All candidates">
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
      </Sec>
    </div>
  );
}

/* ----------------------------------------------------------------- Rewrites */
function RewritesTab({ r }: { r: OptimizeResult }) {
  const lo = r.logical_optimization;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-2">
        <Sec title="Original tree" bodyClass="p-3">
          <PlanFlow root={lo.original_tree} variant="ra" height={400} />
        </Sec>
        <Sec title={<div className="flex items-center gap-2">Optimized tree <Badge tone="ok">rewritten</Badge></div>} bodyClass="p-3">
          <PlanFlow root={lo.optimized_tree} variant="ra" height={400} />
        </Sec>
      </div>
      <Sec bodyClass="p-0" title={<div className="flex items-center gap-2">Transformations {estChip}</div>}>
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
      </Sec>
    </div>
  );
}

/* ------------------------------------------------------------- SQLite plan */
function EnginePlanTab({ r }: { r: OptimizeResult }) {
  const ex = r.explain;
  if (!ex || ex.error) return <Empty title="Unavailable">EXPLAIN comparison unavailable{ex?.error ? `: ${ex.error}` : ""}.</Empty>;
  if (!ex.engine) {
    return <Empty title="Unavailable">This result was saved by an older version and has no SQLite plan data. Re-run the query to see it.</Empty>;
  }
  const c = ex.custom, t = ex.engine;
  return (
    <div className="space-y-4">
      <p className="text-2xs text-faint">
        Right: engine plan (SQLite EXPLAIN QUERY PLAN, what the database will do). Left: candidate plan from this platform's cost model (estimated). They are different things.
      </p>
      <div className="grid gap-4 lg:grid-cols-2">
        <Sec title={<div className="flex items-center gap-2">Custom optimizer <Badge tone="accent">cost model</Badge></div>}>
          <Rows rows={[
            ["Tables", c.tables.join(", ")], ["Scan methods", c.scan_methods.join(", ") || "—"],
            ["Join methods", c.join_methods.join(", ") || "—"], ["Indexes", c.indexes_used.join(", ") || "none"],
            ["Explicit sort", c.has_sort ? "yes" : "no"],
          ]} />
        </Sec>
        <Sec title={<div className="flex items-center gap-2">SQLite <Badge>EXPLAIN QUERY PLAN</Badge></div>}>
          <Rows rows={[
            ["Tables", t.tables.join(", ")], ["Indexes", t.indexes_used.join(", ") || "none"],
            ["Temp B-tree", t.uses_temp_btree ? "yes" : "no"],
          ]} />
          <div className="mt-3 label">Raw steps</div>
          <ol className="mt-1 space-y-1">
            {t.steps.map((s: any, i: number) => (
              <li key={i} className="bg-panel-2 px-2.5 py-1.5 font-mono text-2xs text-muted">{s.detail}</li>
            ))}
          </ol>
        </Sec>
      </div>
      <Sec title="Differences">
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
      </Sec>
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
  const [canCreate, setCanCreate] = useState(false);
  useEffect(() => { api.config().then((c) => setCanCreate(!!c.index_creation_enabled)).catch(() => {}); }, []);
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
          <Sec key={key}>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <code className="bg-panel-2 px-2 py-1 text-xs">{x.index_ddl}</code>
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
                {positive && !canCreate && (
                  <p className="mt-2 max-w-[16rem] text-2xs text-faint">Index creation is disabled (the database is read-only). Set <code>ALLOW_INDEX_CREATION=true</code> in backend/.env to enable it.</p>
                )}
                {positive && canCreate && (
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
          </Sec>
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
      <Sec>
        <div className="flex flex-wrap items-center gap-2">
          <button className="btn btn-ghost text-sm" onClick={() => ask()} disabled={loading}>↻ Re-explain</button>
          <input className="input min-w-[16rem] flex-1 text-sm" placeholder="Ask about this plan…"
            value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && q && ask(q)} />
          <button className="btn btn-primary text-sm" onClick={() => q && ask(q)} disabled={loading || !q}>Ask</button>
        </div>
        <p className="mt-2 text-2xs text-faint">Grounded only in this query's optimizer output — the assistant won't invent metrics.</p>
      </Sec>
      {loading && <Sec><Loading label="Consulting the copilot…" /></Sec>}
      {err && <ErrorNote message={err} />}
      {answer && !loading && (
        <Sec title={<div className="flex items-center gap-2">Explanation <Badge tone={answer.source === "openai" ? "ok" : "neutral"}>{answer.source}{answer.model ? ` · ${answer.model}` : ""}</Badge></div>}>
          {answer.warning && <div className="mb-3 bg-[color:var(--warn-soft)] px-2.5 py-1.5 text-xs text-warn">{answer.warning}</div>}
          <Markdown md={answer.explanation} />
        </Sec>
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
