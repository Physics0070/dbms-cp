// Typed API client. All data comes from the backend — nothing is fabricated here.

export interface Column {
  name: string; data_type: string; nullable: boolean; primary_key: boolean; default: string | null;
}
export interface IndexInfo { name: string; columns: string[]; unique: boolean; origin: string; }
export interface ForeignKey { columns: string[]; ref_table: string; ref_columns: string[]; on_update: string; on_delete: string; }
export interface TableSchema {
  name: string; primary_key: string[]; columns: Column[]; indexes: IndexInfo[];
  foreign_keys: ForeignKey[]; row_count?: number;
}
export interface Relationship { from_table: string; from_columns: string[]; to_table: string; to_columns: string[]; }
export interface SchemaResponse { database_backend: string; tables: TableSchema[]; relationships: Relationship[]; }

export interface PlanNode {
  id: string; operator: string; estimated_rows: number;
  cpu_cost: number; io_cost: number; memory_cost: number; self_total_cost: number; total_cost: number;
  reasoning: string; meta: Record<string, any>; children: PlanNode[];
}
export interface Candidate {
  id: string; join_order: string[]; operators: string[]; join_operators: string[];
  estimated_rows: number; total_cost: number; plan: PlanNode;
}
export interface Example { label: string; kind: string; sql: string; }

export interface OptimizedQuery {
  status: "rewritten" | "no_change" | "unsupported" | "rejected" | "unverified" | "error";
  original_sql: string;
  sql: string | null;
  rejected_sql?: string;
  changes: { name: string; what: string; why: string; tradeoff: string }[];
  reasons: string[];
  original_order: string[];
  join_order: string[];
  estimated: { before_cost: number; after_cost: number; improvement_pct: number; note: string };
  equivalence: {
    checked: boolean; equal: boolean; original_rows?: number; optimized_rows?: number;
    columns_match?: boolean; note: string;
  } | null;
  benchmark: {
    original: any; optimized: any; median_change_pct: number;
    verdict: "faster" | "slower" | "indistinguishable"; note: string; error?: string;
  } | null;
  turso_plan: string[] | null;
}

export interface OptimizeResult {
  sql: string; optimizer_version: string; database_backend: string; statistics_source: string;
  optimization_time_ms: number;
  relational_algebra: any;
  cardinality: { estimated_final_rows: number; per_operator: any[] };
  optimization: {
    method: string; join_orders_considered: number; relations: string[];
    selected_total_cost: number; reason: string;
    selected: Candidate; candidates: Candidate[];
  };
  logical_optimization: {
    original_tree: any; optimized_tree: any;
    transformations: { name: string; description: string; before_cost: number; after_cost: number;
      before_rows: number; after_rows: number; improvement_pct: number; details: any }[];
    overall: { before_cost: number; after_cost: number; improvement_pct: number };
  };
  explain: any;
  optimized_query: OptimizedQuery;
  benchmark: any;
  index_advisor: { baseline_cost: number; recommendations: any[]; note: string } | null;
  summary: any;
  history_id?: string;
}

async function post<T>(url: string, body: any): Promise<T> {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail ?? detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  return r.json();
}
async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText);
  return r.json();
}

export const api = {
  health: () => get<any>("/api/health"),
  config: () => get<any>("/api/config"),
  schema: () => get<SchemaResponse>("/api/schema"),
  examples: () => get<{ examples: Example[] }>("/api/examples"),
  statistics: (table: string) => get<any>(`/api/statistics/${table}`),
  validate: (sql: string) => post<{ valid: boolean; message: string }>("/api/validate", { sql }),
  optimize: (sql: string, opts: { benchmark?: boolean; index_advisor?: boolean } = {}) =>
    post<OptimizeResult>("/api/optimize", { sql, benchmark: opts.benchmark ?? false, index_advisor: opts.index_advisor ?? true }),
  explain: (sql: string) => post<any>("/api/explain", { sql }),
  benchmark: (sql: string) => post<any>("/api/benchmark", { sql }),
  indexAdvisor: (sql: string) => post<any>("/api/index-advisor", { sql }),
  createIndex: (table: string, columns: string[], unique = false) =>
    post<any>("/api/index/create", { table, columns, unique, confirm: true }),
  copilot: (sql: string, question?: string) => post<any>("/api/copilot", { sql, question }),
  history: () => get<{ items: any[] }>("/api/history"),
  historyItem: (id: string) => get<any>(`/api/history/${id}`),
};

export function fmt(n: number | undefined | null, digits = 2): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits });
}
