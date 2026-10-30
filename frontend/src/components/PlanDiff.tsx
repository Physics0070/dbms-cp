// Side-by-side comparison of two candidate plans produced by this platform (estimated costs).
import { useMemo, useState } from "react";
import type { Candidate } from "../api";
import { diffPlans, PlanNodeLike } from "../lib/diff";
import { PlanFlow, TreeNode } from "./PlanFlow";

const label = (c: Candidate, i: number) =>
  `${c.id}: ${c.join_order.length ? c.join_order.join(" ⋈ ") : `plan ${i + 1}`} · est. cost ${c.total_cost.toLocaleString(undefined, { maximumFractionDigits: 1 })}`;

export function PlanDiff({ candidates, selectedId }: { candidates: Candidate[]; selectedId: string }) {
  const sorted = useMemo(() => [...candidates].sort((a, b) => a.total_cost - b.total_cost), [candidates]);
  const [a, setA] = useState(selectedId);
  const [b, setB] = useState(sorted.find((c) => c.id !== selectedId)?.id ?? selectedId);
  const ca = sorted.find((c) => c.id === a) ?? sorted[0], cb = sorted.find((c) => c.id === b) ?? sorted[0];
  const diff = useMemo(() => diffPlans(ca.plan as PlanNodeLike, cb.plan as PlanNodeLike), [ca, cb]);

  if (sorted.length < 2) return <p className="text-sm text-muted">Only one candidate plan was generated, so there is nothing to compare.</p>;

  const Select = ({ v, set, name }: { v: string; set: (s: string) => void; name: string }) => (
    <label className="flex min-w-0 flex-1 flex-col gap-1 text-2xs text-faint">{name}
      <select className="input text-xs" value={v} onChange={(e) => set(e.target.value)}>
        {sorted.map((c, i) => <option key={c.id} value={c.id}>{label(c, i)}</option>)}
      </select>
    </label>
  );
  const delta = cb.total_cost - ca.total_cost;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-3"><Select v={a} set={setA} name="Plan A" /><Select v={b} set={setB} name="Plan B" /></div>
      {a === b ? <p className="text-sm text-muted">Pick two different candidates to compare.</p> : (
        <>
          <p className="text-xs text-muted">
            Estimated cost, not measured runtime: B is {delta === 0 ? "equal to" : `${Math.abs(delta).toLocaleString(undefined, { maximumFractionDigits: 1 })} ${delta > 0 ? "higher than" : "lower than"}`} A.
            Differences are marked with text labels ADDED / REMOVED / CHANGED.
          </p>
          {!diff.reliable ? <p className="text-sm text-warn">Comparison unavailable: {diff.reason}</p> : (
            <>
              <div className="grid gap-3 lg:grid-cols-2">
                <PlanFlow root={ca.plan as unknown as TreeNode} variant="plan" height={380} statusById={diff.statusA}
                  provenance="A · candidate plan (this platform, estimated)" />
                <PlanFlow root={cb.plan as unknown as TreeNode} variant="plan" height={380} statusById={diff.statusB}
                  provenance="B · candidate plan (this platform, estimated)" />
              </div>
              <ul className="space-y-1 text-xs" aria-label="Plan differences">
                {diff.notes.length === 0 && <li className="text-muted">No operator differences found.</li>}
                {diff.notes.map((n, i) => (
                  <li key={i} className="flex gap-2"><span className="chip border border-line-2 bg-panel-3 font-mono text-muted">{n.status}</span><span className="font-mono">{n.text}</span></li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </div>
  );
}
