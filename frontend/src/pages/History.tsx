import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, fmt } from "../api";
import { Empty, Loading, Panel } from "../components/ui";
import { useStore } from "../store";

export default function History() {
  const [items, setItems] = useState<any[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const { loadResult } = useStore();
  const nav = useNavigate();

  useEffect(() => { api.history().then((r) => setItems(r.items)).catch(() => setItems([])); }, []);

  async function reopen(id: string) {
    setBusy(id);
    try { const rec = await api.historyItem(id); loadResult(rec.result, "plan"); nav("/"); }
    finally { setBusy(null); }
  }

  if (!items) return <Loading label="Loading history…" />;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold">Query History</h1>
        <p className="text-sm text-muted">Every optimization is recorded and can be reopened in the workspace.</p>
      </div>
      {items.length === 0 ? (
        <Empty icon="⟲" title="No history yet">Optimize a query and it will appear here.</Empty>
      ) : (
        <Panel bodyClass="p-0">
          <div className="overflow-x-auto">
            <table className="data">
              <thead><tr>
                <th>When</th><th>SQL</th><th className="text-right">Cost</th><th className="text-right">Rows</th>
                <th className="text-right">Cand.</th><th className="text-right">Bench</th><th></th>
              </tr></thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.id}>
                    <td className="whitespace-nowrap text-2xs text-faint">{new Date(it.timestamp).toLocaleString()}</td>
                    <td className="max-w-[22rem] truncate font-mono text-xs" title={it.sql}>{it.sql}</td>
                    <td className="text-right">{fmt(it.estimated_cost)}</td>
                    <td className="text-right">{fmt(it.estimated_rows, 0)}</td>
                    <td className="text-right">{fmt(it.candidate_count, 0)}</td>
                    <td className="text-right text-xs">{it.benchmark && !it.benchmark.error ? `${fmt(it.benchmark.median_ms)}ms` : "—"}</td>
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
        </Panel>
      )}
    </div>
  );
}
