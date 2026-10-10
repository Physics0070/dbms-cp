import { useState } from "react";
import { api, fmt } from "../api";
import { Card, NeedRun, Badge } from "../components/ui";
import { useStore } from "../store";

export default function IndexAdvisor() {
  const { result } = useStore();
  const [created, setCreated] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  if (!result) return <NeedRun />;
  const adv = result.index_advisor;
  if (!adv) return <Card><div className="text-sm text-slate-500">Index advisor was not run for this query.</div></Card>;

  async function create(table: string, columns: string[]) {
    const key = `${table}:${columns.join(",")}`;
    setBusy(key); setErr(null);
    try {
      const r = await api.createIndex(table, columns);
      setCreated((c) => ({ ...c, [key]: r.ddl }));
    } catch (e: any) { setErr(e.message); }
    finally { setBusy(null); }
  }

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold">What-If Index Advisor</h1>
        <p className="text-sm text-slate-500">
          Baseline plan cost: <b>{fmt(adv.baseline_cost)}</b>. Candidates come from the query's WHERE / JOIN / ORDER BY / GROUP BY.
          {" "}Hypothetical only — {adv.note}
        </p>
      </header>

      {err && <div className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{err}</div>}

      {adv.recommendations.length === 0 ? (
        <Card><div className="text-sm text-slate-500">No beneficial hypothetical index was found for this query.</div></Card>
      ) : (
        <div className="space-y-3">
          {adv.recommendations.map((r: any) => {
            const key = `${r.table}:${r.columns.join(",")}`;
            const positive = r.improvement_pct > 0;
            return (
              <Card key={key}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <code className="rounded bg-slate-100 px-2 py-1 text-sm dark:bg-slate-800">{r.index_ddl}</code>
                      <Badge tone="slate">{r.source}</Badge>
                      {r.affected_operator !== "none" && <Badge tone="blue">{r.affected_operator}</Badge>}
                    </div>
                    <p className="mt-2 max-w-2xl text-sm text-slate-600 dark:text-slate-300">{r.reason}</p>
                    <div className="mt-1 text-xs text-slate-500">
                      Overhead: ~{fmt(r.estimated_overhead.index_entries, 0)} index entries. {r.estimated_overhead.note}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-xs text-slate-500">current → hypothetical</div>
                    <div className="text-lg font-semibold tabular-nums">{fmt(r.current_cost)} → {fmt(r.hypothetical_cost)}</div>
                    <Badge tone={positive ? "green" : "slate"}>{fmt(r.improvement_pct)}% {positive ? "cheaper" : "no gain"}</Badge>
                    <div className="mt-2">
                      {created[key] ? (
                        <Badge tone="green">created ✓</Badge>
                      ) : positive ? (
                        <button className="btn btn-ghost" disabled={busy === key} onClick={() => create(r.table, r.columns)}>
                          {busy === key ? "Creating…" : "Create index"}
                        </button>
                      ) : null}
                    </div>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
