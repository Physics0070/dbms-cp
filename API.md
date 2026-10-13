# HTTP API

Base URL: `http://localhost:8000`. All responses are JSON. Secrets
(such as `OPENAI_API_KEY`) are never exposed to any endpoint.

## Health & config

### `GET /api/health`
```json
{ "status": "ok", "database_backend": "SQLite · optimizer_demo.db (read-only)",
  "tables": ["categories","customers","order_items","orders","products"],
  "openai_configured": false }
```

### `GET /api/config`
Non-secret cost-model constants, selectivity defaults and `index_creation_enabled`.

## Schema & statistics

### `GET /api/database`
The connected database: `{ connected, engine, name, path, read_only, tables, table_names }`, or
`{ connected: false, reason }`.

### `POST /api/database/connect`
`{ "path": "C:\\data\\my.db" }` switches to another SQLite file (opened read-only). `400` with a
clear message if the file is missing or is not a SQLite database; the previous connection stays.

### `GET /api/schema`
Full schema: every table with columns, primary key, indexes, foreign keys, row counts,
plus discovered `relationships`.

### `GET /api/examples`
Example queries **generated from the live schema and statistics** (joins from foreign keys,
filters from most-common-value histograms, aggregates from low-cardinality columns) —
never hardcoded. `{ "examples": [ { label, kind, sql } ] }`.

### `GET /api/schema/tables`
`{ "tables": [...] }`

### `GET /api/schema/{table}`
One table's schema. `404` if unknown.

### `GET /api/statistics/{table}`
Computed statistics (row count, per-column distinct/null/min/max/MCV, `collected_at`,
`source`).

## Optimize & analyze

### `POST /api/optimize`
```json
{ "sql": "SELECT ...", "benchmark": false, "index_advisor": true, "save_history": true }
```
Returns the full pipeline result: `relational_algebra`, `cardinality`, `optimization`
(`selected` + `candidates` + `reason`), `logical_optimization` (before/after trees +
transformations), `explain` (SQLite plan comparison), `optimized_query`, `benchmark`,
`index_advisor`, `summary`, and a `history_id`. `400` for non-read-only SQL.

`optimized_query.status` is one of:
- `rewritten` — a reconstructed SQL (`sql`) that changes the join order (pinned with
  `CROSS JOIN … ON`) when the cost model estimates a gain over the query as written. It is only returned after the database confirms it yields the same columns and the
  same multiset of rows (`equivalence`). When `benchmark` is requested, both queries are timed
  and `benchmark.verdict` is `faster`/`slower` only if the measured ranges do not overlap,
  otherwise `indistinguishable`. `estimated` carries cost-model numbers and is labelled as such.
- `no_change` — the query is already in its best form (reasons given).
- `unsupported` — outer joins, subqueries, set operations, `LIMIT/OFFSET` or unresolved
  columns, where a rewrite is not provably safe.
- `rejected` / `unverified` — a candidate rewrite failed (or could not complete) verification
  and is withheld from the optimized output.

### `POST /api/validate`
`{ "sql": "..." }` → `{ "valid": bool, "message": str }`.

### `POST /api/explain`
`{ "sql": "..." }` → parsed `EXPLAIN QUERY PLAN` (+ `EXPLAIN` bytecode when available).

### `POST /api/benchmark`
`{ "sql": "...", "warmup": 2, "runs": 5 }` → Application Benchmark
(min/max/avg/median ms, rows returned).

## Index advisor

### `POST /api/index-advisor`
`{ "sql": "..." }` → `{ baseline_cost, recommendations: [...], note }`.
Each recommendation includes `current_cost`, `hypothetical_cost`, `improvement_pct`,
`affected_operator`, `reason`, `estimated_overhead`, `index_ddl`.

### `POST /api/index/create`  *(opt-in write)*
```json
{ "table": "orders", "columns": ["status"], "unique": false, "confirm": true }
```
Requires `confirm=true` **and** `ALLOW_INDEX_CREATION=true` on the server (`403` otherwise,
because databases are opened read-only by default). Validates identifiers against the schema,
runs `CREATE INDEX`, returns the executed DDL. `400` if not confirmed or identifiers are invalid.

## AI copilot

### `POST /api/copilot`
`{ "sql": "...", "question": "optional" }` → `{ source: "openai"|"offline", model, explanation, warning? }`.
Grounded strictly in the optimizer's structured output; works offline.

## History

### `GET /api/history`
`{ "items": [ { id, timestamp, sql, estimated_cost, estimated_rows, candidate_count, join_order, benchmark, index_recommendations } ] }`

### `GET /api/history/{id}`
The full saved result snapshot for that run (used to reopen it). `404` if not found.
