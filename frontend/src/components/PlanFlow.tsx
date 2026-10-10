import { useMemo, useState } from "react";
import ReactFlow, { Background, Controls, Edge, Handle, Node, NodeProps, Position } from "reactflow";

export interface TreeNode {
  id: string;
  children?: TreeNode[];
  [k: string]: any;
}

export const OP_COLORS: Record<string, string> = {
  SeqScan: "#8b94a1", Scan: "#8b94a1",
  IndexScan: "#38bdf8",
  Filter: "#d8a24a", Selection: "#d8a24a",
  Projection: "#a78bfa",
  NestedLoopJoin: "#e0786e", IndexNestedLoopJoin: "#f0954a",
  HashJoin: "#46b17b", MergeJoin: "#2dd4bf", Join: "#46b17b",
  Aggregate: "#ec6ca0", Sort: "#7aa2ff",
};
export function operatorColor(op: string): string {
  return OP_COLORS[op] || "#8b94a1";
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
}

function FlowNode({ data }: NodeProps<NodeData>) {
  const heat = data.heat ?? 0;
  const heatColor = heat > 0.66 ? "var(--err)" : heat > 0.33 ? "var(--warn)" : "var(--accent)";
  return (
    <div
      className="group relative w-[196px] rounded-lg border bg-panel text-left transition-shadow"
      style={{
        borderColor: data.selected ? data.color : "var(--line)",
        boxShadow: data.selected ? `0 0 0 2px ${data.color}55` : undefined,
      }}
    >
      <Handle type="target" position={Position.Top} />
      <div className="flex items-center gap-2 px-2.5 pt-2">
        <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: data.color }} />
        <span className="truncate text-xs font-semibold text-ink">{data.op}</span>
        {data.collapsedCount != null && data.onToggle && (
          <button
            onClick={(e) => { e.stopPropagation(); data.onToggle!(); }}
            className="ml-auto rounded bg-panel-2 px-1 text-2xs text-muted hover:text-ink"
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
      {data.heat != null && (
        <div className="mx-2.5 mb-2 mt-1.5 h-1 overflow-hidden rounded-full bg-panel-3">
          <div className="h-full rounded-full" style={{ width: `${Math.max(4, heat * 100)}%`, background: heatColor }} />
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
}: {
  root: TreeNode;
  variant: "plan" | "ra";
  onSelect?: (n: TreeNode) => void;
  selectedId?: string;
  height?: number;
  collapsible?: boolean;
}) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const byId = useMemo(() => {
    const m = new Map<string, TreeNode>();
    const walk = (n: TreeNode) => { m.set(n.id, n); (n.children || []).forEach(walk); };
    walk(root);
    return m;
  }, [root]);

  const maxCost = useMemo(() => {
    let mx = 0;
    const walk = (n: TreeNode) => { mx = Math.max(mx, n.total_cost || 0); (n.children || []).forEach(walk); };
    walk(root);
    return mx || 1;
  }, [root]);

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

      const data: NodeData =
        variant === "plan"
          ? {
              op, color,
              line1: `${Number(n.estimated_rows ?? 0).toLocaleString()} rows`,
              line2: undefined,
              detail: `cost ${Number(n.total_cost ?? 0).toLocaleString(undefined, { maximumFractionDigits: 1 })}`,
              heat: (n.total_cost || 0) / maxCost,
              selected: selectedId === n.id,
              collapsedCount: collapsible && (n.children?.length ?? 0) > 0 ? (isCollapsed ? countDesc(n) : 0) : undefined,
              onToggle: collapsible && (n.children?.length ?? 0) > 0
                ? () => setCollapsed((s) => { const n2 = new Set(s); n2.has(n.id) ? n2.delete(n.id) : n2.add(n.id); return n2; })
                : undefined,
            }
          : { op, color, line1: "", detail: raDetail(n), selected: selectedId === n.id };

      ns.push({
        id: n.id, type: "plan", position: { x, y: depth * yGap }, data,
        sourcePosition: Position.Bottom, targetPosition: Position.Top,
        draggable: false, selectable: !!onSelect,
      });
      for (const c of kids) {
        es.push({ id: `${n.id}-${c.id}`, source: n.id, target: c.id,
          style: { stroke: "var(--line-2)", strokeWidth: 1.5 } });
      }
      return x;
    }
    walk(root, 0);
    return { nodes: ns, edges: es };
  }, [root, selectedId, collapsed, maxCost, variant, collapsible, onSelect]);

  return (
    <div className="rounded-lg border border-line bg-[color:var(--bg)]" style={{ height }}>
      <ReactFlow
        nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView minZoom={0.2} maxZoom={1.6}
        nodesDraggable={false} nodesConnectable={false} proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => onSelect?.(byId.get(node.id)!)}
      >
        <Background gap={20} size={1} color="var(--grid)" />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
    </div>
  );
}
