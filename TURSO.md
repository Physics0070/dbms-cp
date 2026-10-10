# Turso / libSQL

## Why Turso/libSQL

- **SQLite-compatible** — a well-understood, embeddable engine with a simple, stable
  metadata model (`sqlite_master`, `PRAGMA …`) that is ideal for teaching schema
  discovery and statistics collection.
- **Serverless & distributed** — Turso runs libSQL at the edge with a lightweight
  client, so the same code runs against a local file *or* a remote replicated database.
- **Zero heavy setup** — a local libSQL/SQLite file needs no server, which makes the demo
  reproducible; the remote path is a single URL + token away.

## Connection strategy (`turso_adapter.py`)

```
TURSO_DATABASE_URL set?  ── yes ──► libsql.connect(sync_url=…, auth_token=…)   → "Turso (remote libSQL)"
        │ no
        ▼
libsql client installed? ── yes ──► libsql.connect(LOCAL_DB_PATH)             → "libSQL (local file)"
        │ no
        ▼
              stdlib sqlite3.connect(LOCAL_DB_PATH)                            → "SQLite (local file, libSQL-compatible)"
```

Because libSQL is SQLite-compatible, the fallback is functionally identical for the
optimizer. `/api/health` reports which backend is active.

## Metadata mechanisms used (all SQLite/libSQL native)

| Purpose | Mechanism |
|---------|-----------|
| Tables | `SELECT name FROM sqlite_master WHERE type='table'` |
| Columns / PK / nullability | `PRAGMA table_info(t)` |
| Indexes | `PRAGMA index_list(t)` + `PRAGMA index_info(i)` |
| Foreign keys | `PRAGMA foreign_key_list(t)` |
| Query plan | `EXPLAIN QUERY PLAN <sql>` |
| Bytecode (optional) | `EXPLAIN <sql>` |
| Read-only guard | `PRAGMA query_only = ON` |

## What we deliberately do **not** use

- No PostgreSQL `pg_catalog` / `information_schema`.
- No PostgreSQL `EXPLAIN ANALYZE` semantics (SQLite has no equivalent runtime metrics),
  so runtime measurement is done by **application-level benchmarking** instead.
- No PostgreSQL-specific SQL or statistics APIs.

## EXPLAIN QUERY PLAN

SQLite's `EXPLAIN QUERY PLAN` returns rows like:
```
SCAN orders
SEARCH customers USING INTEGER PRIMARY KEY (rowid=?)
USE TEMP B-TREE FOR ORDER BY
```
`explain_parser.py` parses these into structured steps (access method, table, index,
temp-b-tree usage) and compares them with our own plan. Differences are expected and
educational — our cost model is an independent estimator, not a reimplementation of
SQLite's planner.

## Index creation (opt-in)

The only write path exposed is `POST /api/index/create`, which requires `confirm=true`,
validates the table/columns against the discovered schema, and runs a parameter-safe
`CREATE INDEX`. It exists so the What-If advisor's suggestions can be applied on demand —
nothing is created automatically.
