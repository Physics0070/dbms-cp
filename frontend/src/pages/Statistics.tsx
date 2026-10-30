import { useEffect, useState } from "react";
import { api, fmt } from "../api";
import { ErrorNote, Loading } from "../components/ui";
import { Meta, PageHeader, Section } from "../components/pagekit";

/** Inline bar: width is value/max, the number beside it carries the exact value. */
function Bar({ ratio, tone = "ink" }: { ratio: number; tone?: "ink" | "accent" }) {
  const w = `${Math.max(0, Math.min(1, ratio)) * 100}%`;
  return (
    <span className="block h-1.5 w-full bg-panel-3" aria-hidden="true">
      <span className="block h-full" style={{ width: w, background: tone === "accent" ? "var(--accent)" : "var(--ink)", opacity: tone === "ink" ? 0.55 : 1 }} />
    </span>
  );
}

export default function Statistics() {
  const [tables, setTables] = useState<{ name: string; rows?: number }[]>([]);
  const [table, setTable] = useState("");
  const [stats, setStats] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.schema().then((s) => {
      setTables(s.tables.map((t) => ({ name: t.name, rows: t.row_count })));
      if (s.tables.length) setTable(s.tables[0].name);
    }).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!table) return;
    setStats(null);
    api.statistics(table).then(setStats).catch((e) => setError(e.message));
  }, [table]);

  if (error) return <ErrorNote message={error} />;

  const cols = stats ? Object.values<any>(stats.columns) : [];
  const rowCount = stats?.row_count ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader index="03" title="Statistics"
        subtitle="Computed live from the connected database with SQL aggregates. These are the numbers the cost model uses to estimate cardinality." />

      <div className="grid gap-6 lg:grid-cols-[200px_1fr]">
        <nav aria-label="Select table" className="lg:sticky lg:top-4 lg:self-start">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-widest text-faint">Tables · {tables.length}</div>
          <ul className="flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible">
            {tables.map((t) => (
              <li key={t.name} className="shrink-0">
                <button onClick={() => setTable(t.name)} aria-current={table === t.name ? "true" : undefined}
                  className={`flex w-full items-baseline justify-between gap-3 border-l-2 px-3 py-1.5 text-left font-mono text-xs transition-colors
                    focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--ring)]
                    ${table === t.name ? "border-accent bg-panel-2 text-ink" : "border-line text-muted hover:text-ink"}`}>
                  <span className="truncate">{t.name}</span>
                  <span className="tabular-nums text-faint">{t.rows != null ? fmt(t.rows, 0) : ""}</span>
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <div className="min-w-0">
          {!stats ? <Loading label={`Collecting statistics for ${table}…`} /> : (
            <div className="space-y-6">
              <dl className="grid grid-cols-2 gap-4 border-y border-line py-4 sm:grid-cols-4">
                <Meta k="Table" v={stats.table ?? table} />
                <Meta k="Rows" v={fmt(stats.row_count, 0)} />
                <Meta k="Source" v={stats.source} />
                <Meta k="Collected" v={new Date(stats.collected_at).toLocaleString()} />
              </dl>

              <Section index="01" title="Column statistics" right={<span className="font-mono text-[10px] uppercase tracking-widest text-faint">bars: distinct ÷ rows · nulls ÷ rows</span>}>
                <div className="overflow-x-auto border border-line" tabIndex={0} role="region" aria-label="Column statistics (scrollable)">
                  <table className="data">
                    <thead><tr>
                      <th>Column</th><th>Type</th><th className="min-w-[9rem]">Distinct</th><th className="min-w-[8rem]">Nulls</th>
                      <th>Min</th><th>Max</th><th>Most common</th>
                    </tr></thead>
                    <tbody>
                      {cols.map((c: any) => (
                        <tr key={c.column}>
                          <td className="font-mono text-xs text-ink">{c.column}</td>
                          <td className="font-mono text-2xs uppercase text-faint">{c.data_type}</td>
                          <td>
                            <div className="flex items-center gap-2">
                              <span className="w-16 shrink-0 text-right font-mono text-xs tabular-nums">{fmt(c.distinct_count, 0)}</span>
                              <Bar ratio={rowCount ? c.distinct_count / rowCount : 0} />
                            </div>
                          </td>
                          <td>
                            <div className="flex items-center gap-2">
                              <span className="w-14 shrink-0 text-right font-mono text-xs tabular-nums">{fmt(c.null_fraction * 100)}%</span>
                              <Bar ratio={c.null_fraction} tone="accent" />
                            </div>
                          </td>
                          <td className="max-w-[7rem] truncate font-mono text-2xs" title={String(c.min_value)}>{String(c.min_value)}</td>
                          <td className="max-w-[7rem] truncate font-mono text-2xs" title={String(c.max_value)}>{String(c.max_value)}</td>
                          <td className="font-mono text-2xs text-faint">{c.most_common.slice(0, 3).map((m: any) => `${m.value}×${m.count}`).join("  ") || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Section>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
