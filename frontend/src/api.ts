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
  original_pretty: string;
  sql: string | null;
  rejected_sql?: string;
  changes: { name: string; what: string; why: string; tradeoff: string }[];
  reasons: string[];
  original_order: string[];
  join_order: string[];
  estimated: {
    before_cost: number; after_cost: number; improvement_pct: number; baseline: string;
    naive_cost: number; naive_improvement_pct: number; naive_baseline: string; note: string;
  };
  equivalence: {
    checked: boolean; equal: boolean; original_rows?: number; optimized_rows?: number;
    columns_match?: boolean; note: string;
  } | null;
  benchmark: {
    original: any; optimized: any; median_change_pct: number;
    verdict: "faster" | "slower" | "indistinguishable"; note: string; error?: string;
  } | null;
  engine_plan: string[] | null;
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
    overall: {
      before_cost: number; after_cost: number; improvement_pct: number; baseline: string;
      naive_cost: number; naive_improvement_pct: number; naive_baseline: string;
    };
  };
  explain: any;
  optimized_query: OptimizedQuery;
  benchmark: any;
  index_advisor: { baseline_cost: number; recommendations: any[]; note: string } | null;
  summary: any;
  history_id?: string;
}

// Optional shared-token auth: the token lives in sessionStorage only and is sent as a Bearer header.
export class UnauthorizedError extends Error {
  constructor() { super("Authentication required."); this.name = "UnauthorizedError"; }
}
export function setApiToken(t: string | null) {
  try { t ? sessionStorage.setItem("qp-token", t) : sessionStorage.removeItem("qp-token"); } catch { /* ignore */ }
}
async function authFetch(url: string, init: RequestInit = {}): Promise<Response> {
  let token: string | null = null;
  try { token = sessionStorage.getItem("qp-token"); } catch { /* ignore */ }
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const r = await fetch(url, { ...init, headers });
  if (r.status === 401) {
    window.dispatchEvent(new Event("qp-unauthorized"));
    throw new UnauthorizedError();
  }
  return r;
}

export interface WorkloadPreview {
  headers: string[]; row_count: number; preview: Record<string, string>[];
  suggested_mapping: Record<string, string | null>;
}
export interface WorkloadGroup {
  rank: number; fingerprint: string; example_sql: string; executions: number; total_ms: number | null;
  avg_ms: number | null; errors: number | null; rows: number | null; derived_total: boolean;
  score: number; share_pct: number; source_lines: number[];
}
export interface WorkloadAnalysis {
  score_basis: string; groups: WorkloadGroup[]; input_rows: number;
  skipped: { line: number; reason: string }[]; skipped_count: number; mapping: Record<string, string | null>;
}
async function workloadPost<T>(url: string, file: File): Promise<T> {
  const r = await authFetch(url, { method: "POST", headers: { "Content-Type": "text/csv" }, body: file });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText);
  return r.json();
}

async function post<T>(url: string, body: any): Promise<T> {
  const r = await authFetch(url, {
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
  const r = await authFetch(url);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText);
  return r.json();
}

export const api = {
  health: () => get<any>("/api/health"),
  config: () => get<any>("/api/config"),
  schema: () => get<SchemaResponse>("/api/schema"),
  examples: () => get<{ examples: Example[] }>("/api/examples"),
  database: () => get<any>("/api/database"),
  connectDatabase: (path: string) => post<any>("/api/database/connect", { path }),
  uploadDatabase: async (file: File) => {
    const r = await authFetch("/api/database/upload", {
      method: "POST", headers: { "Content-Type": "application/octet-stream", "X-Filename": file.name }, body: file,
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText);
    return r.json();
  },
  workloadPreview: (file: File) => workloadPost<WorkloadPreview>("/api/workload/preview", file),
  workloadAnalyze: (file: File, mapping: Record<string, string>) =>
    workloadPost<WorkloadAnalysis>(`/api/workload/analyze?${new URLSearchParams(mapping)}`, file),
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
  labCompare: (body: { baseline_sql: string; candidate_sql: string; warmup: number; runs: number }) =>
    post<LabResult>("/api/lab/compare", body),
  saveInvestigation: (body: { title: string; rationale: string; comparison: LabResult }) =>
    post<any>("/api/investigations", body),
  investigations: () => get<{ items: InvestigationSummary[] }>("/api/investigations"),
  investigation: (id: string) => get<Investigation>(`/api/investigations/${id}`),
  deleteInvestigation: async (id: string) => {
    const r = await authFetch(`/api/investigations/${id}`, { method: "DELETE" });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail ?? r.statusText);
  },
};

export function fmt(n: number | undefined | null, digits = 2): string {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: digits });
}

// --- Benchmark lab / investigations --------------------------------------------------
export interface Timing {
  samples_ms: number[]; min_ms: number; max_ms: number; median_ms: number; iqr_ms: number; rows_returned: number;
}
export interface LabEstimate { available: boolean; cost: number | null; reason?: string; join_order?: string[] }
export interface LabResult {
  baseline_sql: string; candidate_sql: string;
  config: { warmup_runs: number; measured_runs: number };
  estimated: { label: string; baseline: LabEstimate; candidate: LabEstimate };
  measured: {
    label: string; baseline: Timing; candidate: Timing;
    verdict: "faster" | "slower" | "indistinguishable" | "not_comparable"; median_change_pct: number | null;
  };
  equivalence: { checked: boolean; equal: boolean; note: string; original_rows?: number; optimized_rows?: number };
  caveats: string[];
}
export interface InvestigationSummary {
  id: string; created_at: string; title: string; database: string;
  verdict: LabResult["measured"]["verdict"]; median_change_pct: number | null;
  baseline_median_ms: number; candidate_median_ms: number;
}
export interface Investigation {
  id: string; created_at: string; title: string; rationale: string; engine: string; database: string;
  schema_fingerprint: string; optimizer_version: string; comparison: LabResult;
  schema_changed: boolean | null; staleness_note: string | null;
}

// --- Remote database connections (PostgreSQL) ------------------------------------------
export interface RemoteConnection {
  engine: "postgresql" | "mysql"; host: string; port: number; database: string; user: string;
  password: string; sslmode: "disable" | "allow" | "prefer" | "require" | "verify-ca" | "verify-full";
  schema_name?: string;
}
export const remoteApi = {
  test: (c: RemoteConnection) =>
    post<{ ok: boolean; server_version: string; tables: number; capabilities: Record<string, boolean> }>("/api/database/test-remote", c),
  connect: (c: RemoteConnection) => post<any>("/api/database/connect-remote", c),
};
