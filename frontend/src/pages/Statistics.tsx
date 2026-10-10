import { useEffect, useState } from "react";
import { api, fmt } from "../api";
import { GenericBarChart } from "../components/CostChart";
import { Card, Loading, ErrorState } from "../components/ui";

export default function Statistics() {
  const [tables, setTables] = useState<string[]>([]);
  const [table, setTable] = useState<string>("");
  const [stats, setStats] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.schema().then((s) => {
      const names = s.tables.map((t) => t.name);
      setTables(names);
      if (names.length) setTable(names[0]);
    }).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!table) return;
    setStats(null);
    api.statistics(table).then(setStats).catch((e) => setError(e.message));
  }, [table]);

  if (error) return <ErrorState message={error} />;

  const cols = stats ? Object.values<any>(stats.columns) : [];
  const distinctChart = cols.map((c: any) => ({ column: c.column, distinct: c.distinct_count }));

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Statistics</h1>
          <p className="text-sm text-slate-500">Computed from live Turso/libSQL data with SQL aggregates.</p>
        </div>
        <select
          className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
          value={table} onChange={(e) => setTable(e.target.value)}
        >
          {tables.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </header>

      {!stats ? <Loading label={`Collecting statistics for ${table}…`} /> : (
        <>
          <div className="flex flex-wrap items-center gap-3 text-sm text-slate-500">
            <span>Row count: <b className="text-slate-800 dark:text-slate-100">{fmt(stats.row_count, 0)}</b></span>
            <span>·</span>
            <span>Source: {stats.source}</span>
            <span>·</span>
            <span>Collected: {new Date(stats.collected_at).toLocaleString()}</span>
          </div>

          <Card title="Distinct values per column">
            <GenericBarChart data={distinctChart} xKey="column" yKey="distinct" color="#0ea5e9" />
          </Card>

          <Card title="Column statistics">
            <div className="overflow-x-auto">
              <table className="data">
                <thead>
                  <tr>
                    <th>Column</th><th>Type</th><th className="text-right">Distinct</th>
                    <th className="text-right">Nulls</th><th className="text-right">Null frac</th>
                    <th>Min</th><th>Max</th><th>Most common</th>
                  </tr>
                </thead>
                <tbody>
                  {cols.map((c: any) => (
                    <tr key={c.column}>
                      <td className="font-mono">{c.column}</td>
                      <td className="text-slate-500">{c.data_type}</td>
                      <td className="text-right">{fmt(c.distinct_count, 0)}</td>
                      <td className="text-right">{fmt(c.null_count, 0)}</td>
                      <td className="text-right">{fmt(c.null_fraction * 100)}%</td>
                      <td className="max-w-[8rem] truncate" title={String(c.min_value)}>{String(c.min_value)}</td>
                      <td className="max-w-[8rem] truncate" title={String(c.max_value)}>{String(c.max_value)}</td>
                      <td className="text-xs text-slate-500">
                        {c.most_common.slice(0, 3).map((m: any) => `${m.value}×${m.count}`).join(", ") || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
