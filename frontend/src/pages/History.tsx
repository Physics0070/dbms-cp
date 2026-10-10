import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, fmt } from "../api";
import { Card, Loading, Empty } from "../components/ui";
import { useStore } from "../store";

export default function History() {
  const [items, setItems] = useState<any[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const { loadResult } = useStore();
  const nav = useNavigate();

  useEffect(() => { api.history().then((r) => setItems(r.items)).catch(() => setItems([])); }, []);

  async function reopen(id: string) {
    setBusy(id);
    try {
      const rec = await api.historyItem(id);
      loadResult(rec.result);
      nav("/execution-plans");
    } finally { setBusy(null); }
  }

  if (!items) return <Loading label="Loading history…" />;

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold">Query History</h1>
        <p className="text-sm text-slate-500">Every optimization is recorded and can be reopened.</p>
      </header>

      {items.length === 0 ? (
        <Empty>No queries optimized yet.</Empty>
      ) : (
        <Card>
          <div className="overflow-x-auto">
            <table className="data">
              <thead>
                <tr>
                  <th>When</th><th>SQL</th><th className="text-right">Cost</th>
                  <th className="text-right">Rows</th><th className="text-right">Candidates</th>
                  <th className="text-right">Bench (ms)</th><th></th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <tr key={it.id}>
                    <td className="whitespace-nowrap text-xs text-slate-500">{new Date(it.timestamp).toLocaleString()}</td>
                    <td className="max-w-[24rem] truncate font-mono text-xs" title={it.sql}>{it.sql}</td>
                    <td className="text-right">{fmt(it.estimated_cost)}</td>
                    <td className="text-right">{fmt(it.estimated_rows, 0)}</td>
                    <td className="text-right">{fmt(it.candidate_count, 0)}</td>
                    <td className="text-right">{it.benchmark && !it.benchmark.error ? fmt(it.benchmark.median_ms) : "—"}</td>
                    <td><button className="btn btn-ghost" disabled={busy === it.id} onClick={() => reopen(it.id)}>Reopen</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
