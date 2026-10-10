import { useMemo } from "react";
import ReactFlow, { Background, Controls, Edge, Node, MarkerType } from "reactflow";

export interface TreeNode {
  id: string;
  children?: TreeNode[];
  [k: string]: any;
}

const OP_COLORS: Record<string, string> = {
  SeqScan: "#64748b", Scan: "#64748b",
  IndexScan: "#0ea5e9",
  Filter: "#f59e0b", Selection: "#f59e0b",
  Projection: "#8b5cf6",
  NestedLoopJoin: "#ef4444", IndexNestedLoopJoin: "#f97316",
  HashJoin: "#22c55e", MergeJoin: "#14b8a6", Join: "#22c55e",
  Aggregate: "#ec4899", Sort: "#6366f1",
};

function layout(
  root: TreeNode,
  getLabel: (n: TreeNode) => JSX.Element,
  selectedId?: string
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  let leaf = 0;
  const xGap = 240, yGap = 130;

  function walk(n: TreeNode, depth: number): number {
    const kids = n.children || [];
    let x: number;
    if (kids.length === 0) {
      x = leaf * xGap;
      leaf += 1;
    } else {
      const xs = kids.map((c) => walk(c, depth + 1));
      x = xs.reduce((a, b) => a + b, 0) / xs.length;
    }
    const op = n.operator || n.op || "";
    const color = OP_COLORS[op] || "#64748b";
    nodes.push({
      id: n.id,
      position: { x, y: depth * yGap },
      data: { label: getLabel(n) },
      style: {
        width: 200, padding: 0, borderColor: color,
        borderWidth: selectedId === n.id ? 3 : 1.5,
        background: "var(--rf-node-bg, #fff)",
        boxShadow: selectedId === n.id ? `0 0 0 3px ${color}33` : undefined,
      },
      sourcePosition: "bottom" as any,
      targetPosition: "top" as any,
    });
    for (const c of kids) {
      edges.push({
        id: `${n.id}-${c.id}`, source: n.id, target: c.id,
        markerEnd: { type: MarkerType.ArrowClosed },
        style: { stroke: "#94a3b8" },
      });
    }
    return x;
  }
  walk(root, 0);
  return { nodes, edges };
}

export function PlanFlow({
  root, getLabel, onSelect, selectedId, height = 520,
}: {
  root: TreeNode;
  getLabel: (n: TreeNode) => JSX.Element;
  onSelect?: (n: TreeNode) => void;
  selectedId?: string;
  height?: number;
}) {
  const byId = useMemo(() => {
    const m = new Map<string, TreeNode>();
    const walk = (n: TreeNode) => { m.set(n.id, n); (n.children || []).forEach(walk); };
    walk(root);
    return m;
  }, [root]);

  const { nodes, edges } = useMemo(() => layout(root, getLabel, selectedId), [root, selectedId]);

  return (
    <div className="reactflow-wrap rounded-lg border border-slate-200 dark:border-slate-800" style={{ height }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        minZoom={0.2}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        onNodeClick={(_, node) => onSelect?.(byId.get(node.id)!)}
      >
        <Background gap={18} color="#cbd5e1" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}

export function operatorColor(op: string): string {
  return OP_COLORS[op] || "#64748b";
}
