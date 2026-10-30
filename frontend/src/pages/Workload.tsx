import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, WorkloadAnalysis, WorkloadPreview } from "../api";
import { useStore } from "../store";
import { Meta, PageHeader, Section, Tag } from "../components/pagekit";

const FIELDS: [string, string, boolean][] = [
  ["sql", "SQL text", true], ["count", "Execution count", false], ["total_ms", "Total time (ms)", false],
  ["avg_ms", "Average time (ms)", false], ["errors", "Errors", false], ["rows", "Rows", false],
];
const fmt = (n: number | null, d = 1) => (n == null ? "—" : n.toLocaleString(undefined, { maximumFractionDigits: d }));

export default function Workload() {
  const { setSql } = useStore();
  const nav = useNavigate();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<WorkloadPreview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [result, setResult] = useState<WorkloadAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function pick(f: File) {
    setFile(f); setResult(null); setError(null); setBusy(true);
    try {
      const p = await api.workloadPreview(f);
      setPreview(p);
      setMapping(Object.fromEntries(Object.entries(p.suggested_mapping).filter(([, v]) => v) as [string, string][]));
    } catch (e: any) { setPreview(null); setError(e.message); } finally { setBusy(false); }
  }

  async function run() {
    if (!file) return;
    setBusy(true); setError(null);
    try { setResult(await api.workloadAnalyze(file, mapping)); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  const maxShare = result ? Math.max(1, ...result.groups.map((g) => g.share_pct)) : 1;

  return (
    <div className="space-y-8">
      <PageHeader index="04" title="Workloads"
        subtitle="Import a CSV of recorded queries (for example a slow-query log export). Queries are grouped by pattern and ranked using only the columns you map. Nothing is estimated or invented." />

      <Section index="01" title="Import">
        <label className="font-mono text-[10px] uppercase tracking-widest text-faint" htmlFor="wl-file">CSV file</label>
        <input id="wl-file" type="file" accept=".csv,text/csv" className="input mt-1.5 block w-full max-w-md text-xs"
          onChange={(e) => e.target.files?.[0] && pick(e.target.files[0])} />
        <p className="mt-1.5 font-mono text-[10px] text-faint">Max 5 MB · first row must be column names</p>
        {error && <p role="alert" className="mt-3 border border-err px-3 py-2 text-xs text-err">{error}</p>}
      </Section>

      <Section index="02" title="Map columns" className={preview ? "" : "opacity-50"}>
        {!preview ? <p className="text-sm text-muted">Waiting for a file.</p> : (
          <div className="space-y-4">
            <p className="font-mono text-xs text-muted"><span className="tabular-nums text-ink">{preview.row_count.toLocaleString()}</span> rows in {file?.name}</p>
            <div className="grid gap-3 sm:grid-cols-3">
              {FIELDS.map(([key, label, req]) => (
                <label key={key} className="font-mono text-[10px] uppercase tracking-widest text-faint">
                  {label}{req && " *"}
                  <select className="input mt-1 w-full font-sans text-sm normal-case tracking-normal text-ink" value={mapping[key] ?? ""}
                    onChange={(e) => setMapping((m) => { const n = { ...m }; if (e.target.value) n[key] = e.target.value; else delete n[key]; return n; })}>
                    <option value="">{req ? "Choose a column…" : "Not in file"}</option>
                    {preview.headers.map((h) => <option key={h}>{h}</option>)}
                  </select>
                </label>
              ))}
            </div>
            <div className="overflow-x-auto border border-line">
              <table className="data">
                <thead><tr>{preview.headers.map((h) => <th key={h}>{h}</th>)}</tr></thead>
                <tbody>{preview.preview.map((r, i) => (
                  <tr key={i}>{preview.headers.map((h) => <td key={h} className="max-w-[260px] truncate font-mono text-2xs">{r[h]}</td>)}</tr>
                ))}</tbody>
              </table>
            </div>
            <button className="btn btn-primary" onClick={run} disabled={busy || !mapping.sql}>{busy ? "Analyzing…" : "Analyze workload"}</button>
          </div>
        )}
      </Section>

      <Section index="03" title="Ranked patterns" className={result ? "" : "opacity-50"}>
        {!result ? <p className="text-sm text-muted">Results appear here after analysis.</p> : (
          <div className="space-y-4">
            {/* provenance strip */}
            <div className="border border-line bg-panel p-4">
              <p className="font-mono text-xs text-ink">Source: {file?.name}</p>
              <dl className="mt-3 grid grid-cols-2 gap-4 sm:grid-cols-4">
                <Meta k="Rows read" v={result.input_rows.toLocaleString()} />
                <Meta k="Patterns" v={result.groups.length} />
                <Meta k="Ranked by" v={result.score_basis} />
                <Meta k="Mapped" v={Object.entries(result.mapping).filter(([, v]) => v).map(([k, v]) => `${k}=${v}`).join(", ")} />
              </dl>
              {result.skipped_count > 0 && (
                <p className="mt-3 text-xs text-warn">{result.skipped_count} rows skipped (first: line {result.skipped[0].line}, {result.skipped[0].reason}).</p>
              )}
            </div>
            <div className="overflow-x-auto border border-line">
              <table className="data">
                <thead><tr><th>#</th><th>Query pattern</th><th className="text-right">Executions</th><th className="text-right">Total ms</th><th className="text-right">Avg ms</th><th className="min-w-[8rem]">Share</th><th className="text-right">Errors</th><th className="text-right">Rows</th><th /></tr></thead>
                <tbody>{result.groups.map((g) => (
                  <tr key={g.rank}>
                    <td className="font-mono text-accent">{String(g.rank).padStart(2, "0")}</td>
                    <td className="max-w-[420px] truncate font-mono text-2xs" title={g.fingerprint}>{g.fingerprint}</td>
                    <td className="text-right font-mono tabular-nums">{fmt(g.executions, 0)}</td>
                    <td className="text-right font-mono tabular-nums" title={g.derived_total ? "Derived: avg × count" : undefined}>{fmt(g.total_ms)}{g.derived_total && "*"}</td>
                    <td className="text-right font-mono tabular-nums">{fmt(g.avg_ms)}</td>
                    <td>
                      <div className="flex items-center gap-2">
                        <span className="w-12 shrink-0 text-right font-mono text-xs tabular-nums">{g.share_pct}%</span>
                        <span className="block h-1.5 w-full bg-panel-3" aria-hidden="true"><span className="block h-full bg-accent" style={{ width: `${(g.share_pct / maxShare) * 100}%` }} /></span>
                      </div>
                    </td>
                    <td className="text-right font-mono tabular-nums">{fmt(g.errors, 0)}</td>
                    <td className="text-right font-mono tabular-nums">{fmt(g.rows, 0)}</td>
                    <td><button className="btn btn-ghost text-xs" onClick={() => { setSql(g.example_sql); nav("/app"); }}>Open in SQL Lab</button></td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
            <p className="font-mono text-[10px] text-faint">* total derived as average × count. Open in SQL Lab loads a real example statement from your file with its literals unchanged. <Tag>no metrics invented</Tag></p>
          </div>
        )}
      </Section>
    </div>
  );
}
