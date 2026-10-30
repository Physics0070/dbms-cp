import { useEffect, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Meta, PageHeader, Section, Tag } from "../components/pagekit";

interface Rec {
  table: string; columns: string[]; ddl: string; source: string; patterns: string[];
  current_cost: number; hypothetical_cost: number; improvement_pct: number;
  expected_plan_change: string; reason: string; benefit_basis: string;
  assumptions: string[]; tradeoffs: string[];
  estimated_overhead: { index_entries: number; bytes_estimate: number | null; basis: string };
}

export default function IndexLab() {
  const { sql } = useStore();
  const [recs, setRecs] = useState<Rec[] | null>(null);
  const [baseline, setBaseline] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [creationEnabled, setCreationEnabled] = useState(false);
  const [confirming, setConfirming] = useState<Rec | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => { api.config().then((c) => setCreationEnabled(!!c.index_creation_enabled)).catch(() => {}); }, []);

  async function analyze() {
    setBusy(true); setError(null); setNotice(null);
    try {
      const r = await api.indexAdvisor(sql);
      setRecs(r.recommendations); setBaseline(r.baseline_cost);
    } catch (e: any) { setError(e.message || String(e)); setRecs(null); }
    finally { setBusy(false); }
  }

  async function create(r: Rec) {
    try {
      await api.createIndex(r.table, r.columns);
      setNotice(`Created index on ${r.table}(${r.columns.join(", ")}). Re-run the analysis to see the effect.`);
    } catch (e: any) { setError(e.message || String(e)); }
    setConfirming(null);
  }

  const copy = (t: string) => navigator.clipboard?.writeText(t).then(() => setNotice("DDL copied to clipboard."), () => setNotice("Copy failed: select the text manually."));

  return (
    <div className="space-y-8">
      <PageHeader index="05" title="Index Lab"
        subtitle={<>Candidate indexes for the query in your workspace. Benefits are an <b className="font-semibold text-ink">analytical simulation</b> on this tool's cost model
          (this engine has no hypothetical indexes), not measured speedups. Nothing is created unless you confirm it.</>}
        actions={<button className="btn btn-primary" onClick={analyze} disabled={busy || !sql.trim()}>{busy ? "Analyzing…" : "Analyze indexes"}</button>} />

      <Section index="01" title="Query under analysis">
        <pre className="max-h-32 overflow-auto whitespace-pre-wrap border-l-2 border-accent bg-panel p-3 font-mono text-xs text-muted">{sql || "No query yet: write one in the Workspace."}</pre>
      </Section>

      {error && <p role="alert" className="border border-err px-3 py-2 text-sm text-err">{error}</p>}
      {notice && <p role="status" className="border border-ok px-3 py-2 text-sm text-ok">{notice}</p>}

      <Section index="02" title="Recommendation ledger" right={baseline != null && <span className="font-mono text-[10px] uppercase tracking-widest text-faint">baseline cost <span className="tabular-nums text-ink">{baseline}</span> · abstract units</span>}>
        {!recs && <p className="text-sm text-muted">Run the analysis to list candidate indexes.</p>}
        {recs && recs.length === 0 && <p className="text-sm text-muted">No useful candidate indexes found for this query: its filter and join columns are already indexed or the model would not use a new one.</p>}

        <ol className="divide-y divide-line border-y border-line">
          {recs?.map((r, n) => {
            const helps = r.improvement_pct > 0;
            return (
              <li key={r.ddl} className="grid gap-4 py-5 lg:grid-cols-[3rem_1fr_16rem]">
                <span className="font-mono text-xs text-accent">{String(n + 1).padStart(2, "0")}</span>
                <div className="min-w-0 space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-semibold">{r.table}({r.columns.join(", ")})</span>
                    <Tag tone="warn" title="Not measured: estimated by this tool's cost model">Analytical simulation</Tag>
                  </div>
                  <p className="text-sm text-muted">{r.reason}</p>
                  <pre className="overflow-x-auto border border-line bg-bg p-2.5 font-mono text-xs text-ink">{r.ddl}</pre>
                  <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
                    <div><dt className="font-mono text-[10px] uppercase tracking-widest text-faint">Addresses</dt><dd className="text-muted">{r.patterns.join("; ")}</dd></div>
                    <div><dt className="font-mono text-[10px] uppercase tracking-widest text-faint">Expected plan change</dt><dd className="text-muted">{r.expected_plan_change}</dd></div>
                  </dl>
                  <details className="text-sm"><summary className="cursor-pointer font-mono text-[11px] uppercase tracking-widest text-muted hover:text-ink">Assumptions and trade-offs</summary>
                    <ul className="mt-2 list-disc space-y-1 pl-5 text-muted">{[...r.assumptions, ...r.tradeoffs].map((a) => <li key={a}>{a}</li>)}</ul>
                  </details>
                </div>
                <div className="space-y-3 lg:border-l lg:border-line lg:pl-4">
                  <dl className="space-y-2">
                    <Meta k="Est. cost" v={<span className={helps ? "text-accent" : "text-faint"}>{r.current_cost} → {r.hypothetical_cost}{helps && ` (−${r.improvement_pct}%)`}</span>} />
                    <Meta k="Storage" v={r.estimated_overhead.bytes_estimate != null ? `≈ ${(r.estimated_overhead.bytes_estimate / 1024).toFixed(1)} KiB` : "unavailable"} />
                    <p className="font-mono text-[10px] leading-snug text-faint">{r.estimated_overhead.basis}</p>
                  </dl>
                  <div className="flex flex-wrap gap-2">
                    <button className="btn btn-primary text-xs" onClick={() => copy(r.ddl)}>Copy DDL</button>
                    <button className="btn btn-ghost text-xs" onClick={() => setConfirming(r)} disabled={!creationEnabled}
                      title={creationEnabled ? "Create this index in the connected database" : "Disabled: the server opens the database read-only (ALLOW_INDEX_CREATION=false)"}>
                      Create index…
                    </button>
                  </div>
                  {!creationEnabled && <p className="font-mono text-[10px] text-faint">Creation disabled: read-only database.</p>}
                </div>
              </li>
            );
          })}
        </ol>
      </Section>

      <ConfirmDialog open={!!confirming} danger title="This modifies your database" confirmLabel="Create index"
        onCancel={() => setConfirming(null)} onConfirm={() => confirming && create(confirming)}>
        {confirming && (<>
          <p className="text-sm text-muted">Running this statement changes the schema and slows writes to <b>{confirming.table}</b>. It cannot be undone from this tool.</p>
          <pre className="mt-3 overflow-x-auto border border-line bg-bg p-2 font-mono text-xs">{confirming.ddl}</pre>
        </>)}
      </ConfirmDialog>
    </div>
  );
}
