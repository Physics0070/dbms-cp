import { fmt } from "../api";
import { CostBarChart } from "../components/CostChart";
import { Card, NeedRun, Badge } from "../components/ui";
import { useStore } from "../store";

export default function CandidatePlans() {
  const { result } = useStore();
  if (!result) return <NeedRun />;

  const opt = result.optimization;
  const selectedId = opt.selected.id;
  const rows = [...opt.candidates].sort((a, b) => a.total_cost - b.total_cost);
  const chart = rows.map((c, i) => ({
    id: c.id,
    label: c.join_order.length ? c.join_order.join("⋈") : `plan ${i + 1}`,
    cost: c.total_cost,
  }));

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold">Candidate Plans</h1>
        <p className="text-sm text-slate-500">
          {opt.method} — {fmt(opt.join_orders_considered, 0)} join order(s) considered,{" "}
          {rows.length} candidate(s) shown, sorted by total cost. The selected plan is highlighted.
        </p>
      </header>

      <Card title="Cost comparison">
        <CostBarChart data={chart} selectedId={selectedId} />
      </Card>

      <Card title="Candidates">
        <div className="overflow-x-auto">
          <table className="data">
            <thead>
              <tr>
                <th>#</th><th>Join order</th><th>Join methods</th><th>Operators</th>
                <th className="text-right">Est. rows</th><th className="text-right">Total cost</th><th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c, i) => (
                <tr key={c.id} className={c.id === selectedId ? "bg-brand-50 dark:bg-brand-950/30" : ""}>
                  <td>{i + 1}</td>
                  <td className="font-mono">{c.join_order.join(" ⋈ ") || "—"}</td>
                  <td>{[...new Set(c.join_operators)].join(", ") || "—"}</td>
                  <td className="text-xs text-slate-500">{[...new Set(c.operators)].join(", ")}</td>
                  <td className="text-right">{fmt(c.estimated_rows, 0)}</td>
                  <td className="text-right font-semibold">{fmt(c.total_cost)}</td>
                  <td>{c.id === selectedId && <Badge tone="green">selected</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
