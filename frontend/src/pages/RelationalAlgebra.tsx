import { fmt } from "../api";
import { PlanFlow, TreeNode } from "../components/PlanFlow";
import { Card, NeedRun, Badge } from "../components/ui";
import { useStore } from "../store";

function raLabel(n: TreeNode) {
  const op = n.op as string;
  let detail = "";
  switch (op) {
    case "Scan": detail = n.alias === n.table ? n.table : `${n.table} AS ${n.alias}`; break;
    case "Selection": detail = n.predicate_text; break;
    case "Projection": detail = n.is_star ? "*" : (n.columns || []).join(", "); break;
    case "Join": detail = `${n.join_type} · ${n.condition_text}`; break;
    case "Aggregate": detail = `group ${JSON.stringify(n.group_by)} ${(n.aggregates || []).join(", ")}`; break;
    case "Sort": detail = (n.keys || []).join(", "); break;
  }
  return (
    <div className="px-2.5 py-1.5 text-slate-800">
      <div className="font-semibold">{op}</div>
      <div className="truncate font-mono text-[10px] text-slate-500" title={detail}>{detail}</div>
    </div>
  );
}

export default function RelationalAlgebra() {
  const { result } = useStore();
  if (!result) return <NeedRun />;
  const lo = result.logical_optimization;

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold">Relational Algebra</h1>
        <p className="text-sm text-slate-500">Original tree (as parsed) vs the logically-optimized tree.</p>
      </header>

      <div className="grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Card title={<span>Original tree</span>}>
          <PlanFlow root={lo.original_tree} getLabel={raLabel} height={460} />
        </Card>
        <Card title={<span>Optimized tree <Badge tone="green">pushdowns + reorder</Badge></span>}>
          <PlanFlow root={lo.optimized_tree} getLabel={raLabel} height={460} />
        </Card>
      </div>

      <Card title="Logical transformations">
        <table className="data">
          <thead>
            <tr><th>Transformation</th><th>Before</th><th>After</th><th>Improvement</th><th>Description</th></tr>
          </thead>
          <tbody>
            {lo.transformations.map((t) => (
              <tr key={t.name}>
                <td className="font-medium">{t.name}</td>
                <td className="text-right">{fmt(t.before_cost)}</td>
                <td className="text-right">{fmt(t.after_cost)}</td>
                <td className="text-right">
                  <Badge tone={t.improvement_pct > 0 ? "green" : "slate"}>{fmt(t.improvement_pct)}%</Badge>
                </td>
                <td className="text-slate-500">{t.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-3 text-sm text-slate-500">
          Overall: cost {fmt(lo.overall.before_cost)} → {fmt(lo.overall.after_cost)}{" "}
          (<b>{fmt(lo.overall.improvement_pct)}%</b> lower).
        </div>
      </Card>
    </div>
  );
}
