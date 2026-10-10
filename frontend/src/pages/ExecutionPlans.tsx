import { useState } from "react";
import { fmt } from "../api";
import { operatorColor, PlanFlow, TreeNode } from "../components/PlanFlow";
import { Card, NeedRun, Stat } from "../components/ui";
import { useStore } from "../store";

function planLabel(n: TreeNode) {
  return (
    <div className="px-2.5 py-1.5 text-slate-800">
      <div className="flex items-center justify-between">
        <span className="font-semibold">{n.operator}</span>
        <span className="text-[10px] text-slate-500">{fmt(n.estimated_rows, 0)} rows</span>
      </div>
      <div className="font-mono text-[10px] text-slate-500">cost {fmt(n.total_cost)}</div>
    </div>
  );
}

export default function ExecutionPlans() {
  const { result } = useStore();
  const [sel, setSel] = useState<TreeNode | null>(null);
  if (!result) return <NeedRun />;

  const plan = result.optimization.selected.plan;
  const node = sel || plan;

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold">Execution Plans</h1>
        <p className="text-sm text-slate-500">
          The lowest-cost physical plan. Click a node to inspect its operator, rows and cost breakdown.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <Card title="Selected physical plan" className="lg:col-span-2">
          <PlanFlow root={plan} getLabel={planLabel} onSelect={setSel} selectedId={sel?.id} height={540} />
        </Card>

        <div className="space-y-3">
          <Card title="Operator detail">
            <div className="mb-3 flex items-center gap-2">
              <span className="inline-block h-3 w-3 rounded-full" style={{ background: operatorColor(node.operator) }} />
              <span className="text-lg font-semibold">{node.operator}</span>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Stat label="Est. rows" value={fmt(node.estimated_rows, 0)} />
              <Stat label="Total cost" value={fmt(node.total_cost)} />
              <Stat label="CPU" value={fmt(node.cpu_cost)} />
              <Stat label="I/O" value={fmt(node.io_cost)} />
              <Stat label="Memory" value={fmt(node.memory_cost)} />
              <Stat label="Self cost" value={fmt(node.self_total_cost)} />
            </div>
            <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">{node.reasoning}</p>
            {node.meta && Object.keys(node.meta).length > 0 && (
              <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-50 p-3 text-[11px] dark:bg-slate-950">
                {JSON.stringify(node.meta, null, 2)}
              </pre>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
