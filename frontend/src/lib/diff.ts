/** Minimal line diff (longest common subsequence). Returns the 0-based indices of lines
 *  that were removed from `a` and added in `b`. No dependency — SQL here is a few dozen lines. */
export function diffLines(a: string, b: string): { removed: Set<number>; added: Set<number> } {
  const x = a.split("\n").map((l) => l.trim());
  const y = b.split("\n").map((l) => l.trim());
  const n = x.length, m = y.length;
  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = x[i] === y[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const removed = new Set<number>();
  const added = new Set<number>();
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (x[i] === y[j]) { i++; j++; }
    else if (lcs[i + 1][j] >= lcs[i][j + 1]) removed.add(i++);
    else added.add(j++);
  }
  while (i < n) removed.add(i++);
  while (j < m) added.add(j++);
  return { removed, added };
}

export type PlanDiffStatus = "same" | "changed" | "added" | "removed";
export interface PlanNodeLike { id: string; operator?: string; total_cost?: number; estimated_rows?: number; meta?: any; children?: PlanNodeLike[] }
export interface PlanDiffResult {
  reliable: boolean;
  reason?: string;
  statusA: Record<string, PlanDiffStatus>;
  statusB: Record<string, PlanDiffStatus>;
  notes: { status: PlanDiffStatus; text: string }[];
}

const JOINS = new Set(["HashJoin", "NestedLoopJoin", "IndexNestedLoopJoin", "MergeJoin", "Join"]);

/** Flatten a plan into (key -> node). A node's key is derived from the relations beneath it
 *  (scan aliases) and its operator class, so the same logical step matches across plans even if
 *  the join order differs. If a scan lacks an alias/table the diff is declared unreliable. */
function index(root: PlanNodeLike): { map: Map<string, PlanNodeLike>; ok: boolean } {
  const map = new Map<string, PlanNodeLike>();
  let ok = true;
  const walk = (n: PlanNodeLike): string[] => {
    const kids = n.children || [];
    let rels: string[];
    if (!kids.length) {
      const r = n.meta?.alias || n.meta?.table;
      if (!r) ok = false;
      rels = r ? [String(r)] : [];
    } else rels = kids.flatMap(walk);
    const op = n.operator || "";
    let key = `${JOINS.has(op) ? "join" : op}|${[...rels].sort().join(",")}`;
    for (let i = 2; map.has(key); i++) key = `${key}#${i}`;
    map.set(key, n);
    return rels;
  };
  walk(root);
  return { map, ok };
}

export function diffPlans(a: PlanNodeLike, b: PlanNodeLike): PlanDiffResult {
  const A = index(a), B = index(b);
  const out: PlanDiffResult = { reliable: A.ok && B.ok, statusA: {}, statusB: {}, notes: [] };
  if (!out.reliable) { out.reason = "A scan operator has no relation name, so operators cannot be matched reliably."; return out; }
  const pct = (x?: number, y?: number) => (x && y ? Math.abs(x - y) / Math.max(x, y) : 0);
  for (const [k, na] of A.map) {
    const nb = B.map.get(k);
    const label = `${na.operator} on ${k.split("|")[1] || "?"}`;
    if (!nb) { out.statusA[na.id] = "removed"; out.notes.push({ status: "removed", text: `${label} only in A` }); continue; }
    const opChanged = na.operator !== nb.operator;
    const idxChanged = (na.meta?.index || null) !== (nb.meta?.index || null);
    const costChanged = pct(na.total_cost, nb.total_cost) > 0.005;
    const st: PlanDiffStatus = opChanged || idxChanged || costChanged ? "changed" : "same";
    out.statusA[na.id] = out.statusB[nb.id] = st;
    if (st === "changed") {
      const why = [opChanged && `${na.operator} → ${nb.operator}`, idxChanged && `index ${na.meta?.index ?? "none"} → ${nb.meta?.index ?? "none"}`,
        costChanged && `est. cost ${Number(na.total_cost).toFixed(1)} → ${Number(nb.total_cost).toFixed(1)}`].filter(Boolean).join("; ");
      out.notes.push({ status: "changed", text: `${label}: ${why}` });
    }
  }
  for (const [k, nb] of B.map) {
    if (!A.map.has(k)) { out.statusB[nb.id] = "added"; out.notes.push({ status: "added", text: `${nb.operator} on ${k.split("|")[1] || "?"} only in B` }); }
  }
  return out;
}
