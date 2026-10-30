import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, fmt, Investigation, InvestigationSummary } from "../api";
import { Empty, ErrorNote, Loading } from "../components/ui";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Meta, PageHeader, Section, Tag, tabCls } from "../components/pagekit";
import { useStore } from "../store";

export default function History() {
  const [tab, setTab] = useState<"queries" | "investigations">("queries");
  return (
    <div className="space-y-6">
      <PageHeader index="07" title="History" subtitle="Past optimizations and saved benchmark investigations."
        actions={
          <div className="flex border-b border-line">
            <button className={tabCls(tab === "queries")} aria-pressed={tab === "queries"} onClick={() => setTab("queries")}>Queries</button>
            <button className={tabCls(tab === "investigations")} aria-pressed={tab === "investigations"} onClick={() => setTab("investigations")}>Investigations</button>
          </div>} />
      {tab === "queries" ? <QueryHistory /> : <Investigations />}
    </div>
  );
}

function QueryHistory() {
  const [items, setItems] = useState<any[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const { loadResult } = useStore();
  const nav = useNavigate();

  useEffect(() => { api.history().then((r) => setItems(r.items)).catch(() => setItems([])); }, []);

  async function reopen(id: string) {
    setBusy(id);
    try { const rec = await api.historyItem(id); loadResult(rec.result, "plan"); nav("/app"); }
    finally { setBusy(null); }
  }

  if (!items) return <Loading label="Loading history…" />;
  if (items.length === 0) return <Empty icon="⟲" title="No history yet">Optimize a query and it will appear here.</Empty>;
  return (
    <Section index="01" title="Optimized queries" right={<span className="font-mono text-[10px] uppercase tracking-widest text-faint">{items.length} saved</span>}>
      <div className="overflow-x-auto border border-line">
        <table className="data">
          <thead><tr>
            <th>When</th><th>SQL</th><th className="text-right">Est. cost</th><th className="text-right">Est. rows</th>
            <th className="text-right">Cand.</th><th className="text-right">Measured</th><th></th>
          </tr></thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.id}>
                <td className="whitespace-nowrap font-mono text-2xs text-faint">{new Date(it.timestamp).toLocaleString()}</td>
                <td className="max-w-[22rem] truncate font-mono text-xs" title={it.sql}>{it.sql}</td>
                <td className="text-right font-mono tabular-nums">{fmt(it.estimated_cost)}</td>
                <td className="text-right font-mono tabular-nums">{fmt(it.estimated_rows, 0)}</td>
                <td className="text-right font-mono tabular-nums">{fmt(it.candidate_count, 0)}</td>
                <td className="text-right font-mono text-xs tabular-nums">{it.benchmark && !it.benchmark.error ? `${fmt(it.benchmark.median_ms)}ms` : "—"}</td>
                <td className="text-right">
                  <button className="btn btn-ghost !py-1 text-2xs" disabled={busy === it.id} onClick={() => reopen(it.id)}>
                    {busy === it.id ? "…" : "Reopen"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

const verdictTone = (v: string) => (v === "faster" ? "ok" : v === "slower" ? "err" : v === "not_comparable" ? "warn" : "neutral") as "ok" | "err" | "warn" | "neutral";

function Investigations() {
  const [items, setItems] = useState<InvestigationSummary[] | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [open, setOpen] = useState<Investigation[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  const load = () => api.investigations().then((r) => setItems(r.items)).catch((e) => { setItems([]); setError(e.message); });
  useEffect(() => { load(); }, []);

  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id].slice(-2)));
  async function view() {
    setError(null);
    try { setOpen(await Promise.all(picked.map((id) => api.investigation(id)))); }
    catch (e: any) { setError(e.message || String(e)); }
  }
  async function remove(id: string) {
    await api.deleteInvestigation(id);
    setPicked((p) => p.filter((x) => x !== id)); setOpen([]); setDeleting(null); load();
  }

  if (!items) return <Loading label="Loading investigations…" />;
  if (items.length === 0) return <Empty icon="⏱" title="No investigations yet">Run a comparison in the Lab and save it to keep the evidence.</Empty>;

  return (
    <div className="space-y-8">
      {error && <ErrorNote message={error} />}
      <Section index="01" title="Saved investigations"
        right={<div className="flex items-center gap-3">
          <span className="font-mono text-[10px] uppercase tracking-widest text-faint">select one to open, two to compare</span>
          <button className="btn btn-primary !py-1 text-xs" disabled={picked.length === 0} onClick={view}>
            {picked.length === 2 ? "Compare selected" : "Open selected"}
          </button></div>}>
        <div className="overflow-x-auto border border-line">
          <table className="data">
            <thead><tr><th></th><th>Title</th><th>Database</th><th>Saved</th><th className="text-right">Baseline ms</th><th className="text-right">Candidate ms</th><th>Verdict</th><th></th></tr></thead>
            <tbody>
              {items.map((it) => (
                <tr key={it.id}>
                  <td><input type="checkbox" aria-label={`Select ${it.title}`} checked={picked.includes(it.id)} onChange={() => toggle(it.id)} /></td>
                  <td className="text-ink">{it.title}</td>
                  <td className="font-mono text-xs">{it.database}</td>
                  <td className="whitespace-nowrap font-mono text-2xs text-faint">{new Date(it.created_at).toLocaleString()}</td>
                  <td className="text-right font-mono tabular-nums">{fmt(it.baseline_median_ms, 3)}</td>
                  <td className="text-right font-mono tabular-nums">{fmt(it.candidate_median_ms, 3)}</td>
                  <td><Tag tone={verdictTone(it.verdict)}>{it.verdict.replace("_", " ")}</Tag></td>
                  <td className="whitespace-nowrap text-right font-mono text-2xs">
                    <a className="text-accent underline-offset-2 hover:underline" href={`/api/investigations/${it.id}/export?format=md`} download={`${it.title}.md`}>Report</a>{" · "}
                    <a className="text-accent underline-offset-2 hover:underline" href={`/api/investigations/${it.id}/export?format=json`} download={`${it.id}.json`}>JSON</a>{" · "}
                    <button className="text-err underline-offset-2 hover:underline" onClick={() => setDeleting(it.id)}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      {open.length === 2 && <CompareStrip a={open[0]} b={open[1]} />}
      {open.length > 0 && (
        <div className={`grid gap-6 ${open.length === 2 ? "md:grid-cols-2" : ""}`}>
          {open.map((inv) => <InvestigationCard key={inv.id} inv={inv} />)}
        </div>
      )}

      <ConfirmDialog open={!!deleting} danger title="Delete this investigation?" confirmLabel="Delete"
        onCancel={() => setDeleting(null)} onConfirm={() => deleting && remove(deleting)}>
        The saved evidence cannot be recovered.
      </ConfirmDialog>
    </div>
  );
}

/** Metric-by-metric comparison of two saved investigations (recorded values only). */
function CompareStrip({ a, b }: { a: Investigation; b: Investigation }) {
  const rows: [string, (i: Investigation) => string][] = [
    ["Estimated cost, baseline → candidate", (i) => `${i.comparison.estimated.baseline.available ? fmt(i.comparison.estimated.baseline.cost) : "n/a"} → ${i.comparison.estimated.candidate.available ? fmt(i.comparison.estimated.candidate.cost) : "n/a"}`],
    ["Measured median ms, baseline → candidate", (i) => `${fmt(i.comparison.measured.baseline.median_ms, 3)} → ${fmt(i.comparison.measured.candidate.median_ms, 3)}`],
    ["Verdict", (i) => i.comparison.measured.verdict.replace("_", " ")],
    ["Results equivalent", (i) => (i.comparison.equivalence.equal ? "yes" : "no / not verified")],
    ["Database", (i) => `${i.engine} ${i.database}`],
  ];
  return (
    <Section index="02" title="Side by side">
      <div className="overflow-x-auto border border-line">
        <table className="data">
          <thead><tr><th>Metric</th><th>{a.title}</th><th>{b.title}</th></tr></thead>
          <tbody>{rows.map(([k, f]) => (
            <tr key={k}><td className="font-mono text-[10px] uppercase tracking-widest text-faint">{k}</td><td className="font-mono text-xs tabular-nums">{f(a)}</td><td className="font-mono text-xs tabular-nums">{f(b)}</td></tr>
          ))}</tbody>
        </table>
      </div>
    </Section>
  );
}

function InvestigationCard({ inv }: { inv: Investigation }) {
  const c = inv.comparison, m = c.measured;
  return (
    <article className="border border-line bg-panel">
      <header className="border-b border-line px-4 py-3">
        <h3 className="font-display text-2xl font-light tracking-tight">{inv.title}</h3>
      </header>
      <div className="space-y-3 p-4">
        {inv.staleness_note && (
          <p role="alert" className="border border-warn px-3 py-2 text-xs text-warn">{inv.staleness_note}</p>
        )}
        <p className="border-l-2 border-line-2 bg-panel-2 px-3 py-2 text-2xs text-muted">
          Historical evidence recorded {new Date(inv.created_at).toLocaleString()} on {inv.engine} “{inv.database}”.
          It is not a guarantee of current performance.
        </p>
        {inv.rationale && <p className="text-sm"><span className="text-muted">Why: </span>{inv.rationale}</p>}
        <dl className="grid grid-cols-2 gap-4">
          <Meta k="Est. cost (A → B)" v={`${c.estimated.baseline.available ? fmt(c.estimated.baseline.cost) : "n/a"} → ${c.estimated.candidate.available ? fmt(c.estimated.candidate.cost) : "n/a"}`} />
          <Meta k="Median ms (A → B)" v={`${fmt(m.baseline.median_ms, 3)} → ${fmt(m.candidate.median_ms, 3)}`} />
          <Meta k="Range ms" v={`${fmt(m.baseline.min_ms, 3)}–${fmt(m.baseline.max_ms, 3)} / ${fmt(m.candidate.min_ms, 3)}–${fmt(m.candidate.max_ms, 3)}`} />
          <Meta k="Runs" v={`${c.config.warmup_runs} warm-up + ${c.config.measured_runs}`} />
          <Meta k="Verdict" v={<>{m.verdict.replace("_", " ")}{m.median_change_pct !== null && ` (${fmt(m.median_change_pct)}%)`}</>} />
          <Meta k="Equivalent" v={c.equivalence.equal ? "Yes (recorded data)" : "No / not verified"} />
        </dl>
        <pre className="overflow-x-auto border border-line bg-bg p-2 font-mono text-2xs">{c.baseline_sql}</pre>
        <pre className="overflow-x-auto border border-line bg-bg p-2 font-mono text-2xs">{c.candidate_sql}</pre>
      </div>
    </article>
  );
}
