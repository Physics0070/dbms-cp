import { useEffect, useState } from "react";
import { api, fmt } from "../api";
import { GenericBarChart } from "../components/CostChart";
import { ErrorNote, Loading, Panel } from "../components/ui";

export default function Statistics() {
  const [tables, setTables] = useState<string[]>([]);
  const [table, setTable] = useState("");
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

  if (error) return <ErrorNote message={error} />;

  const cols = stats ? Object.values<any>(stats.columns) : [];
  const chart = cols.map((c: any) => ({ column: c.column, distinct: c.distinct_count }));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Statistics</h1>
          <p className="text-sm text-muted">Computed live from the connected database with SQL aggregates.</p>
        </div>
        <select className="input" value={table} onChange={(e) => setTable(e.target.value)} aria-label="Select table">
          {tables.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>

      {!stats ? <Loading label={`Collecting statistics for ${table}…`} /> : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
            <span>Rows <b className="tabular-nums text-ink">{fmt(stats.row_count, 0)}</b></span>
            <span className="text-faint">·</span>
            <span>{stats.source}</span>
            <span className="text-faint">·</span>
            <span>collected {new Date(stats.collected_at).toLocaleString()}</span>
          </div>

          <Panel title="Distinct values per column">
            <GenericBarChart data={chart} xKey="column" yKey="distinct" unit="distinct" />
          </Panel>

          <Panel bodyClass="p-0" title="Column statistics">
            <div className="overflow-x-auto">
              <table className="data">
                <thead><tr>
                  <th>Column</th><th>Type</th><th className="text-right">Distinct</th><th className="text-right">Nulls</th>
                  <th className="text-right">Null %</th><th>Min</th><th>Max</th><th>Most common</th>
                </tr></thead>
                <tbody>
                  {cols.map((c: any) => (
                    <tr key={c.column}>
                      <td className="font-mono text-xs">{c.column}</td>
                      <td className="text-xs text-muted">{c.data_type}</td>
                      <td className="text-right">{fmt(c.distinct_count, 0)}</td>
                      <td className="text-right">{fmt(c.null_count, 0)}</td>
                      <td className="text-right">{fmt(c.null_fraction * 100)}%</td>
                      <td className="max-w-[7rem] truncate text-xs" title={String(c.min_value)}>{String(c.min_value)}</td>
                      <td className="max-w-[7rem] truncate text-xs" title={String(c.max_value)}>{String(c.max_value)}</td>
                      <td className="text-2xs text-faint">{c.most_common.slice(0, 3).map((m: any) => `${m.value}×${m.count}`).join(", ") || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </div>
      )}
    </div>
  );
}
