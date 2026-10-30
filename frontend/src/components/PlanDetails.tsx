// Operator detail panel + SQL fragment highlight for a candidate plan node.
// Only fields the optimizer really produced are shown; the rest say "unavailable".
import type { ReactNode } from "react";
import { operatorColor, TreeNode } from "./PlanFlow";

const num = (v: any, d = 2) =>
  v == null || Number.isNaN(Number(v)) ? "unavailable" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d });

function Row({ k, children, unavailable }: { k: string; children: ReactNode; unavailable?: boolean }) {
  return (
    <div className="grid grid-cols-[110px_1fr] gap-2 border-b border-line py-1.5 text-xs last:border-0">
      <dt className="text-faint">{k}</dt>
      <dd className={`min-w-0 break-words ${unavailable ? "italic text-faint" : "font-mono text-ink"}`}>{children}</dd>
    </div>
  );
}

/** Terms of the SQL text that this operator reliably corresponds to (scan alias/table, join condition). */
export function sqlTerms(node: any, sql: string): { exact: string[]; words: string[] } {
  const meta = node?.meta || {};
  const squash = (s: string) => s.replace(/\s+/g, " ").toLowerCase();
  const hay = squash(sql);
  const words = [meta.alias, meta.table].filter((x): x is string => !!x && hay.includes(String(x).toLowerCase()));
  const exact = [meta.condition, ...(meta.predicates || [])]
    .filter((x): x is string => typeof x === "string" && x.length > 2 && hay.includes(squash(x)));
  return { exact, words };
}

export function SqlHighlight({ sql, node }: { sql: string; node: any }) {
  const { exact, words } = sqlTerms(node, sql);
  if (!exact.length && !words.length) {
    return <p className="text-2xs italic text-faint">No SQL fragment can be matched reliably to this operator.</p>;
  }
  const esc = (s: string) => s.trim().split(/\s+/).map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("\\s+");
  const re = new RegExp(
    [...exact.map(esc), ...words.map((w) => `\\b${esc(w)}\\b`)].join("|"), "gi",
  );
  const parts: ReactNode[] = [];
  let last = 0, m: RegExpExecArray | null;
  while ((m = re.exec(sql))) {
    if (m.index > last) parts.push(sql.slice(last, m.index));
    parts.push(<mark key={m.index} className="bg-[color:var(--accent-soft)] px-0.5 text-ink underline decoration-accent">{m[0]}</mark>);
    last = m.index + m[0].length;
    if (m[0].length === 0) re.lastIndex++;
  }
  parts.push(sql.slice(last));
  return <pre className="max-h-40 overflow-auto whitespace-pre-wrap border border-line bg-panel-2 p-2.5 font-mono text-2xs text-muted">{parts}</pre>;
}

export function PlanDetails({ node, sql }: { node: TreeNode; sql?: string }) {
  const n: any = node, meta = n.meta || {};
  const relation = meta.table ? (meta.alias && meta.alias !== meta.table ? `${meta.table} AS ${meta.alias}` : meta.table) : null;
  const preds: string[] = meta.predicates || [];
  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        <span className="h-3 w-3" style={{ background: operatorColor(n.operator) }} />
        <span className="font-mono text-sm font-medium uppercase tracking-wider">{n.operator}</span>
      </div>
      <dl>
        <Row k="Relation" unavailable={!relation}>{relation ?? "n/a (not a scan)"}</Row>
        <Row k="Access / index" unavailable={!meta.access && !meta.index}>
          {meta.index ? `index ${meta.index}${meta.index_columns ? ` (${meta.index_columns.join(", ")})` : ""}` : meta.access ?? "n/a"}
        </Row>
        <Row k="Predicates" unavailable={!preds.length}>{preds.length ? preds.join(" AND ") : "none on this operator"}</Row>
        <Row k="Join condition" unavailable={!meta.condition}>{meta.condition ?? "n/a (not a join)"}</Row>
        <Row k="Estimated rows">{num(n.estimated_rows, 0)}</Row>
        <Row k="Actual rows" unavailable>unavailable: plans are estimates; no per-operator actuals are collected</Row>
        <Row k="Estimated cost">{num(n.total_cost)} total · {num(n.self_total_cost)} self</Row>
        <Row k="cpu / io / memory">{num(n.cpu_cost)} / {num(n.io_cost)} / {num(n.memory_cost)}</Row>
        <Row k="Actual time" unavailable>unavailable: not measured per operator</Row>
        <Row k="Statistics" unavailable={meta.join_selectivity == null && meta.build_rows == null}>
          {[meta.join_selectivity && `selectivity: ${meta.join_selectivity}`, meta.build_rows != null && `build rows: ${num(meta.build_rows, 0)}`]
            .filter(Boolean).join(" · ") || "none recorded for this operator"}
        </Row>
      </dl>
      {n.reasoning && <p className="mt-3 text-sm text-muted">{n.reasoning}</p>}
      {sql && (
        <div className="mt-3">
          <div className="label mb-1">Matching SQL</div>
          <SqlHighlight sql={sql} node={n} />
        </div>
      )}
    </div>
  );
}
