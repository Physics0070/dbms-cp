import { useMemo, useState } from "react";
import ReactFlow, { Background, Controls, Edge, Handle, MiniMap, Node, NodeProps, Position } from "reactflow";
import type { PlanDiffStatus } from "../lib/diff";

export interface TreeNode {
  id: string;
  children?: TreeNode[];
  [k: string]: any;
}

export const OP_COLORS: Record<string, string> = {
  SeqScan: "#8d887c", Scan: "#8d887c",
  IndexScan: "#efeadf",
  Filter: "#f0b34a", Selection: "#f0b34a",
  Projection: "#c9c3b5",
  NestedLoopJoin: "#ff5a1f", IndexNestedLoopJoin: "#ff8a4d",
  HashJoin: "#d9d3c4", MergeJoin: "#bdb7a8", Join: "#d9d3c4",
  Aggregate: "#a39e92", Sort: "#b4ae9f",
};
export function operatorColor(op: string): string {
  return OP_COLORS[op] || "#8d887c";
}

function raDetail(n: TreeNode): string {
  switch (n.op) {
    case "Scan": return n.alias === n.table ? n.table : `${n.table} → ${n.alias}`;
    case "Selection": return n.predicate_text || "";
    case "Projection": return n.is_star ? "*" : (n.columns || []).join(", ");
    case "Join": return `${n.join_type} · ${n.condition_text}`;
    case "Aggregate": return `γ ${(n.group_by || []).join(", ")} ${(n.aggregates || []).join(", ")}`.trim();
    case "Sort": return (n.keys || []).join(", ");
    default: return "";
  }
}

interface NodeData {
  op: string; color: string;
  line1: string; line2?: string; detail?: string;
  heat?: number; selected?: boolean;
  collapsedCount?: number; onToggle?: () => void;
  tier?: "high" | "medium" | "low"; aria?: string; dim?: boolean;
  status?: PlanDiffStatus; onPick?: () => void;
}

const TIER_MARK = { high: "▲▲ HIGH", medium: "▲ MED", low: "LOW" } as const;
const STATUS_LABEL: Record<string, string> = { added: "ADDED", removed: "REMOVED", changed: "CHANGED" };

function FlowNode({ data }: NodeProps<NodeData>) {
  const heat = data.heat ?? 0;
  const heatColor = heat > 0.66 ? "var(--accent)" : heat > 0.33 ? "var(--warn)" : "var(--faint)";
  return (
    <div
      className="group relative w-[196px] bg-panel text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--ring)]"
      role="button" tabIndex={0} aria-label={data.aria} aria-pressed={!!data.selected}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); data.onPick?.(); } }}
      style={{
        // Cost tier is also encoded by border weight/style and a text label, not colour alone.
        borderWidth: data.tier === "high" ? 3 : 1,
        borderStyle: data.tier === "high" ? "double" : data.tier === "medium" ? "dashed" : "solid",
        borderColor: data.selected ? "var(--ink)" : data.tier === "high" ? "var(--accent)" : "var(--line-2)",
        opacity: data.dim ? 0.3 : 1,
        outline: data.status && data.status !== "same" ? "2px solid var(--warn)" : undefined,
      }}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center gap-2 px-2.5 pt-2">
        <span className="h-2.5 w-2.5 shrink-0" style={{ background: data.color }} />
        <span className="truncate font-mono text-[11px] font-medium uppercase tracking-wider text-ink">{data.op}</span>
        {data.status && STATUS_LABEL[data.status] && (
          <span className="chip bg-[color:var(--warn-soft)] text-warn">{STATUS_LABEL[data.status]}</span>
        )}
        {data.collapsedCount != null && data.onToggle && (
          <button
            onClick={(e) => { e.stopPropagation(); data.onToggle!(); }}
            className="ml-auto border border-line bg-panel-2 px-1 text-2xs text-muted hover:text-ink"
            title={data.collapsedCount > 0 ? "Expand subtree" : "Collapse subtree"}
          >
            {data.collapsedCount > 0 ? `+${data.collapsedCount}` : "−"}
          </button>
        )}
      </div>
      {data.line1 && <div className="px-2.5 pt-0.5 font-mono text-2xs text-faint">{data.line1}</div>}
      {data.detail && (
        <div className="truncate px-2.5 pt-0.5 font-mono text-2xs text-muted" title={data.detail}>
          {data.detail}
        </div>
      )}
      {data.tier && <div className={`px-2.5 pt-0.5 font-mono text-[10px] font-semibold tracking-wider ${data.tier === "high" ? "text-accent" : "text-muted"}`}>{TIER_MARK[data.tier]}</div>}
      {data.heat != null && (
        <div className="mx-2.5 mb-2 mt-1.5 h-[3px] overflow-hidden bg-panel-3" aria-hidden="true">
          <div className="h-full" style={{ width: `${Math.max(4, heat * 100)}%`, background: heatColor }} />
        </div>
      )}
      {data.heat == null && <div className="pb-2" />}
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

const nodeTypes = { plan: FlowNode };

export function PlanFlow({
  root, variant, onSelect, selectedId, height = 460, collapsible = false,
  searchable = false, statusById, provenance, edgeTone = "neutral",
}: {
  root: TreeNode;
  variant: "plan" | "ra";
  onSelect?: (n: TreeNode) => void;
  selectedId?: string;
  height?: number;
  collapsible?: boolean;
  searchable?: boolean;
  statusById?: Record<string, PlanDiffStatus>;
  provenance?: string;
  /** "ok" (lime) is reserved for the plan the optimizer selected. */
  edgeTone?: "ok" | "neutral";
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");

  const byId = useMemo(() => {
    const m = new Map<string, TreeNode>();
    const walk = (n: TreeNode) => { m.set(n.id, n); (n.children || []).forEach(walk); };
    walk(root);
    return m;
  }, [root]);

  // Heat = an operator's own (self) cost relative to the most expensive operator in this plan.
  const maxCost = useMemo(() => {
    let mx = 0;
    const walk = (n: TreeNode) => { mx = Math.max(mx, n.self_total_cost ?? n.total_cost ?? 0); (n.children || []).forEach(walk); };
    walk(root);
    return mx || 1;
  }, [root]);

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return null;
    const hit = new Set<string>();
    byId.forEach((n, id) => {
      const hay = [n.operator, n.op, n.meta?.table, n.meta?.alias, n.meta?.index, n.meta?.condition, ...(n.meta?.predicates || [])]
        .filter(Boolean).join(" ").toLowerCase();
      if (hay.includes(q)) hit.add(id);
    });
    return hit;
  }, [query, byId]);

  const { nodes, edges } = useMemo(() => {
    const ns: Node[] = [];
    const es: Edge[] = [];
    let leaf = 0;
    const xGap = 228, yGap = 116;

    function countDesc(n: TreeNode): number {
      return (n.children || []).reduce((a, c) => a + 1 + countDesc(c), 0);
    }

    function walk(n: TreeNode, depth: number): number {
      const op = n.operator || n.op || "";
      const color = operatorColor(op);
      const isCollapsed = collapsed.has(n.id);
      const kids = isCollapsed ? [] : n.children || [];

      let x: number;
      if (kids.length === 0) { x = leaf * xGap; leaf += 1; }
      else x = kids.map((c) => walk(c, depth + 1)).reduce((a, b) => a + b, 0) / kids.length;

      const heatV = (n.self_total_cost ?? n.total_cost ?? 0) / maxCost;
      const tier = heatV > 0.66 ? "high" : heatV > 0.33 ? "medium" : "low";
      const costTxt = Number(n.total_cost ?? 0).toLocaleString(undefined, { maximumFractionDigits: 1 });
      const status = statusById?.[n.id];
      const common = {
        dim: matches ? !matches.has(n.id) : false,
        status,
        onPick: onSelect ? () => onSelect(n) : undefined,
      };
      const data: NodeData =
        variant === "plan"
          ? {
              ...common,
              op, color,
              line1: `${Number(n.estimated_rows ?? 0).toLocaleString()} rows (est.)`,
              line2: undefined,
              detail: `cost ${costTxt}`,
              heat: heatV, tier,
              aria: `${op}, estimated rows ${Number(n.estimated_rows ?? 0)}, estimated cost ${costTxt}, ${tier} cost tier (${Math.round(heatV * 100)}% of the most expensive operator)${status && status !== "same" ? `, ${status} versus the other plan` : ""}`,
              selected: selectedId === n.id,
              collapsedCount: collapsible && (n.children?.length ?? 0) > 0 ? (isCollapsed ? countDesc(n) : 0) : undefined,
              onToggle: collapsible && (n.children?.length ?? 0) > 0
                ? () => setCollapsed((s) => { const n2 = new Set(s); n2.has(n.id) ? n2.delete(n.id) : n2.add(n.id); return n2; })
                : undefined,
            }
          : { ...common, op, color, line1: "", detail: raDetail(n), aria: `${op} ${raDetail(n)}`, selected: selectedId === n.id };

      ns.push({
        id: n.id, type: "plan", position: { x, y: depth * yGap }, data,
        sourcePosition: Position.Bottom, targetPosition: Position.Top,
        draggable: false, selectable: !!onSelect,
      });
      for (const c of kids) {
        es.push({ id: `${n.id}-${c.id}`, source: n.id, target: c.id,
          style: { stroke: edgeTone === "ok" ? "var(--ok)" : "var(--line-2)", strokeWidth: 1.5 } });
      }
      return x;
    }
    walk(root, 0);
    return { nodes: ns, edges: es };
  }, [root, selectedId, collapsed, maxCost, variant, collapsible, onSelect, matches, statusById, edgeTone]);

  return (
    <div className="relative border border-line bg-[color:var(--bg)]" style={{ height }}>
      {(provenance || searchable) && (
        <div className="absolute left-2 top-2 z-10 flex flex-wrap items-center gap-2">
          {provenance && <span className="chip border border-line bg-panel-2 font-mono text-muted normal-case tracking-normal">{provenance}</span>}
          {searchable && (
            <input className="input !py-1 text-xs" type="search" placeholder="Filter operators…" aria-label="Filter operators"
              value={query} onChange={(e) => setQuery(e.target.value)} />
          )}
          {matches && <span className="text-2xs text-muted" role="status">{matches.size} match{matches.size === 1 ? "" : "es"}</span>}
        </div>
      )}
      <ReactFlow
        nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.22 }} minZoom={0.2} maxZoom={1.6}
        nodesDraggable={false} nodesConnectable={false} proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => onSelect?.(byId.get(node.id)!)}
      >
        <Background gap={20} size={1} color="var(--grid)" />
        <Controls showInteractive={false} position="bottom-right" />
        {height >= 400 && <MiniMap pannable zoomable ariaLabel="Plan overview" position="bottom-left" maskColor="rgba(14,15,17,0.55)" style={{ width: 120, height: 80, background: "var(--panel)", border: "1px solid var(--line)" }}
          nodeColor={(n) => (n.data as NodeData).color} />}
      </ReactFlow>
    </div>
  );
}

/** Plain-text rendering of a candidate plan (estimates only), for the clipboard. */
export function planToText(n: any, depth = 0): string {
  const m = n.meta || {};
  const rel = m.table ? ` ${m.table}${m.alias && m.alias !== m.table ? ` AS ${m.alias}` : ""}` : "";
  const idx = m.index ? ` [index ${m.index}]` : "";
  const line = `${"  ".repeat(depth)}${n.operator}${rel}${idx}  est.rows=${Math.round(n.estimated_rows)}  est.cost=${Number(n.total_cost).toFixed(2)}`;
  return [line, ...(n.children || []).map((c: any) => planToText(c, depth + 1))].join("\n");
}
