import { useEffect, useMemo, useState } from "react";
import ReactFlow, {
  Background, Controls, Edge, Handle, MarkerType, MiniMap, Node, NodeProps, Position, ReactFlowProvider, useReactFlow,
} from "reactflow";
import { api, fmt, SchemaResponse, TableSchema } from "../api";
import { ErrorNote, Loading } from "../components/ui";
import { PageHeader, Tag, tabCls } from "../components/pagekit";
import { useStore } from "../store";

interface TableData { table: TableSchema; selected: boolean; dim: boolean; }

function TableNode({ data }: NodeProps<TableData>) {
  const t = data.table;
  const fkCols = new Set(t.foreign_keys.flatMap((f) => f.columns));
  return (
    <div className={`w-[210px] border bg-panel text-left transition-opacity ${data.dim ? "opacity-30" : ""}`}
      style={{ borderColor: data.selected ? "var(--ink)" : "var(--line-2)" }}>
      <Handle type="target" position={Position.Left} />
      <div className="flex items-baseline justify-between gap-2 border-b border-line bg-panel-2 px-2.5 py-1.5">
        <span className="truncate font-mono text-xs font-semibold text-ink">{t.name}</span>
        <span className="shrink-0 font-mono text-[10px] tabular-nums text-faint">{fmt(t.row_count, 0)}</span>
      </div>
      <ul className="px-2.5 py-1.5 font-mono text-[10px]">
        {t.columns.slice(0, 5).map((c) => (
          <li key={c.name} className="flex justify-between gap-2 leading-5">
            <span className="truncate text-muted">{c.name}</span>
            <span className={c.primary_key ? "text-warn" : "text-accent"}>{c.primary_key ? "PK" : fkCols.has(c.name) ? "FK" : ""}</span>
          </li>
        ))}
        {t.columns.length > 5 && <li className="text-faint">+{t.columns.length - 5} more</li>}
      </ul>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { table: TableNode };

/** Grid layout, most-connected tables first so hubs sit at the top-left. */
function layout(tables: TableSchema[], degree: Map<string, number>) {
  const sorted = [...tables].sort((a, b) => (degree.get(b.name) ?? 0) - (degree.get(a.name) ?? 0) || a.name.localeCompare(b.name));
  const cols = Math.max(1, Math.ceil(Math.sqrt(sorted.length)));
  return new Map(sorted.map((t, i) => [t.name, { x: (i % cols) * 300, y: Math.floor(i / cols) * 210 }]));
}

// SVG marker/minimap fills do not reliably resolve var(), so read the live token values.
const token = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";

function Graph({ schema }: { schema: SchemaResponse }) {
  const { theme } = useStore();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [neighboursOnly, setNeighboursOnly] = useState(false);
  const { fitView } = useReactFlow();

  const { positions, neighbours } = useMemo(() => {
    const degree = new Map<string, number>(), nb = new Map<string, Set<string>>();
    for (const r of schema.relationships) {
      for (const [a, b] of [[r.from_table, r.to_table], [r.to_table, r.from_table]]) {
        degree.set(a, (degree.get(a) ?? 0) + 1);
        (nb.get(a) ?? nb.set(a, new Set()).get(a)!).add(b);
      }
    }
    return { positions: layout(schema.tables, degree), neighbours: nb };
  }, [schema]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return schema.tables.filter((t) => {
      if (neighboursOnly && selected && t.name !== selected && !neighbours.get(selected)?.has(t.name)) return false;
      return !q || t.name.toLowerCase().includes(q) || t.columns.some((c) => c.name.toLowerCase().includes(q));
    });
  }, [schema, query, neighboursOnly, selected, neighbours]);

  const names = useMemo(() => new Set(visible.map((t) => t.name)), [visible]);
  const colors = useMemo(() => ({ hot: token("--ok"), idle: token("--line-2"), node: token("--line-2"), mask: token("--bg") }), [theme]); // eslint-disable-line react-hooks/exhaustive-deps

  const nodes: Node<TableData>[] = visible.map((t) => ({
    id: t.name, type: "table", position: positions.get(t.name)!,
    data: { table: t, selected: t.name === selected, dim: !!selected && t.name !== selected && !neighbours.get(selected)?.has(t.name) },
  }));
  const edges: Edge[] = schema.relationships
    .filter((r) => names.has(r.from_table) && names.has(r.to_table))
    .map((r, i) => {
      const hot = !!selected && (r.from_table === selected || r.to_table === selected);
      return {
        id: `e${i}`, source: r.from_table, target: r.to_table,
        label: r.from_columns.join(","), labelStyle: { fontSize: 10, fill: "var(--muted)", fontFamily: "JetBrains Mono, monospace" },
        labelBgStyle: { fill: "var(--bg)" },
        markerEnd: { type: MarkerType.ArrowClosed, color: hot ? colors.hot : colors.idle },
        style: { stroke: hot ? colors.hot : colors.idle, strokeWidth: hot ? 2 : 1 },
      };
    });

  // Re-fit when the visible set changes (search / neighbour filter).
  useEffect(() => { const id = setTimeout(() => fitView({ padding: 0.2, duration: 200 }), 30); return () => clearTimeout(id); }, [names, fitView]);

  const sel = schema.tables.find((t) => t.name === selected) ?? null;
  return (
    <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)_300px]">
      {/* left: filter column */}
      <aside className="space-y-4" aria-label="Schema filters">
        <div>
          <label htmlFor="schema-search" className="font-mono text-[10px] uppercase tracking-widest text-faint">Search</label>
          <input id="schema-search" className="input mt-1.5 w-full text-xs" placeholder="table or column…" aria-label="Search tables or columns"
            value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <label className={`flex items-center gap-2 font-mono text-[11px] ${selected ? "text-muted" : "text-faint"}`}>
          <input type="checkbox" checked={neighboursOnly} disabled={!selected} onChange={(e) => setNeighboursOnly(e.target.checked)} />
          Selected + neighbours only
        </label>
        <button className="btn btn-ghost w-full text-xs" onClick={() => fitView({ padding: 0.2, duration: 200 })}>Fit view</button>
        <div>
          <div className="mb-1.5 font-mono text-[10px] uppercase tracking-widest text-faint">Tables · {visible.length}/{schema.tables.length}</div>
          <ul className="max-h-[320px] overflow-y-auto border-t border-line">
            {visible.map((t) => (
              <li key={t.name}>
                <button onClick={() => setSelected(t.name === selected ? null : t.name)} aria-pressed={t.name === selected}
                  className={`flex w-full items-baseline justify-between gap-2 border-b border-line px-2 py-1.5 text-left font-mono text-xs
                    focus-visible:outline focus-visible:outline-2 focus-visible:outline-[color:var(--ring)]
                    ${t.name === selected ? "bg-panel-2 text-ink" : "text-muted hover:text-ink"}`}>
                  <span className="truncate">{t.name}</span><span className="tabular-nums text-faint">{fmt(t.row_count, 0)}</span>
                </button>
              </li>
            ))}
          </ul>
          {visible.length === 0 && <p className="pt-2 text-xs text-muted">No tables match “{query}”.</p>}
        </div>
      </aside>

      {/* center: canvas */}
      <div className="h-[calc(100vh-15rem)] min-h-[460px] border border-line bg-bg" role="application" aria-label="Schema relationship graph">
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView minZoom={0.15} nodesConnectable={false}
          onNodeClick={(_, n) => setSelected(n.id)} onPaneClick={() => setSelected(null)}>
          <Background gap={24} color="var(--grid)" />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable nodeColor={colors.node} maskColor={colors.mask + "cc"} style={{ background: "var(--panel)", border: "1px solid var(--line)" }} />
        </ReactFlow>
      </div>

      {/* right: detail drawer */}
      <TableDetail table={sel} schema={schema} />
    </div>
  );
}

function TableDetail({ table, schema }: { table: TableSchema | null; schema: SchemaResponse }) {
  if (!table) return (
    <aside className="border border-line p-4" aria-label="Table details">
      <div className="font-mono text-[10px] uppercase tracking-widest text-faint">Details</div>
      <p className="mt-2 text-sm text-muted">Select a table to see its columns, keys and indexes. Edges of the selected table turn lime.</p>
    </aside>
  );
  const incoming = schema.relationships.filter((r) => r.to_table === table.name);
  return (
    <aside className="border border-line" aria-label="Table details">
      <header className="flex items-baseline justify-between gap-2 border-b border-line bg-panel-2 px-3 py-2">
        <span className="truncate font-mono text-sm font-semibold">{table.name}</span>
        <span className="font-mono text-[10px] tabular-nums text-faint">{fmt(table.row_count, 0)} rows</span>
      </header>
      <div className="max-h-[calc(100vh-18rem)] overflow-y-auto">
        <table className="data">
          <thead><tr><th>Column</th><th>Type</th><th>Key</th></tr></thead>
          <tbody>
            {table.columns.map((c) => {
              const fk = table.foreign_keys.find((f) => f.columns.includes(c.name));
              return (
                <tr key={c.name}>
                  <td className="font-mono text-xs">{c.name}{!c.nullable && <span className="text-faint"> *</span>}</td>
                  <td className="font-mono text-[10px] uppercase text-faint">{c.data_type}</td>
                  <td className="space-x-1 text-2xs">{c.primary_key && <Tag tone="warn">PK</Tag>}{fk && <Tag tone="accent">→ {fk.ref_table}</Tag>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="space-y-2 border-t border-line p-3 text-xs">
          <div className="font-mono text-[10px] uppercase tracking-widest text-faint">Indexes</div>
          {table.indexes.length === 0 ? <p className="text-faint">No indexes.</p> : (
            <div className="flex flex-wrap gap-1.5">
              {table.indexes.map((i) => <Tag key={i.name} tone={i.unique ? "accent" : "neutral"}>{i.name} ({i.columns.join(", ")}){i.unique ? " · uniq" : ""}</Tag>)}
            </div>
          )}
          {incoming.length > 0 && (<>
            <div className="pt-1 font-mono text-[10px] uppercase tracking-widest text-faint">Referenced by</div>
            <ul className="font-mono text-2xs text-muted">{incoming.map((r, i) => <li key={i}>{r.from_table}.{r.from_columns.join(",")}</li>)}</ul>
          </>)}
          <p className="pt-1 font-mono text-[10px] text-faint">* NOT NULL</p>
        </div>
      </div>
    </aside>
  );
}

function ListView({ schema }: { schema: SchemaResponse }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {schema.tables.map((t) => <TableDetail key={t.name} table={t} schema={schema} />)}
    </div>
  );
}

export default function SchemaExplorer() {
  const [schema, setSchema] = useState<SchemaResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"graph" | "list">("graph");

  useEffect(() => { api.schema().then(setSchema).catch((e) => setError(e.message)); }, []);
  if (error) return <ErrorNote message={error} />;
  if (!schema) return <Loading label="Discovering schema…" />;

  return (
    <div className="space-y-5">
      <PageHeader index="02" title="Schema"
        subtitle={<>Discovered from {schema.database_backend} · <span className="font-mono">{schema.tables.length}</span> tables · <span className="font-mono">{schema.relationships.length}</span> foreign keys.</>}
        actions={
          <div role="tablist" aria-label="Schema view" className="flex border-b border-line">
            {(["graph", "list"] as const).map((v) => (
              <button key={v} role="tab" aria-selected={view === v} className={tabCls(view === v)} onClick={() => setView(v)}>
                {v === "graph" ? "Graph" : "List"}
              </button>
            ))}
          </div>} />
      {view === "graph" ? <ReactFlowProvider><Graph schema={schema} /></ReactFlowProvider> : <ListView schema={schema} />}
    </div>
  );
}
