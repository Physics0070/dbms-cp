import { Card, NeedRun, Badge } from "../components/ui";
import { useStore } from "../store";

export default function TursoComparison() {
  const { result } = useStore();
  if (!result) return <NeedRun />;
  const ex = result.explain;
  if (!ex || ex.error) {
    return <Card><div className="text-sm text-slate-500">EXPLAIN comparison unavailable: {ex?.error || "no data"}.</div></Card>;
  }
  const custom = ex.custom;
  const turso = ex.turso;

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold">Turso / SQLite Plan Comparison</h1>
        <p className="text-sm text-slate-500">
          Our independent cost-based plan vs SQLite/libSQL <code>EXPLAIN QUERY PLAN</code>. {ex.note}
        </p>
      </header>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card title={<span>Custom optimizer plan <Badge tone="blue">cost model</Badge></span>}>
          <dl className="space-y-2 text-sm">
            <Row k="Tables" v={custom.tables.join(", ")} />
            <Row k="Scan methods" v={custom.scan_methods.join(", ") || "—"} />
            <Row k="Join methods" v={custom.join_methods.join(", ") || "—"} />
            <Row k="Indexes used" v={custom.indexes_used.join(", ") || "none"} />
            <Row k="Explicit sort" v={custom.has_sort ? "yes" : "no"} />
          </dl>
        </Card>

        <Card title={<span>Turso query plan <Badge tone="slate">EXPLAIN QUERY PLAN</Badge></span>}>
          <dl className="space-y-2 text-sm">
            <Row k="Tables" v={turso.tables.join(", ")} />
            <Row k="Indexes used" v={turso.indexes_used.join(", ") || "none"} />
            <Row k="Temp B-tree (sort/group)" v={turso.uses_temp_btree ? "yes" : "no"} />
          </dl>
          <div className="mt-3">
            <div className="mb-1 text-xs font-semibold uppercase text-slate-400">Raw steps</div>
            <ol className="space-y-1 text-xs">
              {turso.steps.map((s: any, i: number) => (
                <li key={i} className="rounded bg-slate-50 px-2 py-1 font-mono dark:bg-slate-950">{s.detail}</li>
              ))}
            </ol>
          </div>
        </Card>
      </div>

      <Card title="Differences">
        {ex.differences.length === 0 ? (
          <div className="text-sm text-green-700 dark:text-green-300">The two plans agree on tables, index usage and sorting.</div>
        ) : (
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {ex.differences.map((d: string, i: number) => <li key={i}>{d}</li>)}
          </ul>
        )}
      </Card>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-4 border-b border-slate-100 pb-1 dark:border-slate-800">
      <dt className="text-slate-500">{k}</dt>
      <dd className="font-mono">{v}</dd>
    </div>
  );
}
