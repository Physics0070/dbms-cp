# Database support

## What is supported

**Any SQLite database file.** That covers the demo databases, application databases, and
exports from other tools. Nothing in the optimizer knows a table or column name; everything
is discovered from the connected file at request time.

Other engines (PostgreSQL, MySQL, ...) are **not supported**. They would each need their own
adapter, their own `EXPLAIN` parser, and their own statistics source, and the optimizer's cost
model has only been validated against SQLite.

## The adapter layer

The optimizer depends only on the `DatabaseAdapter` interface (`app/database/adapter.py`):

```
get_tables / get_columns / get_indexes / get_foreign_keys / get_schema
get_statistics        execute_readonly
explain_query         explain_bytecode        benchmark_query
```

`SqliteAdapter` (`app/database/sqlite_adapter.py`) implements it with SQLite's own mechanisms:

| Purpose | Mechanism |
|---|---|
| Tables | `SELECT name FROM sqlite_master WHERE type='table'` |
| Columns / keys / nullability | `PRAGMA table_info(t)` |
| Indexes | `PRAGMA index_list(t)` and `PRAGMA index_info(i)` |
| Foreign keys | `PRAGMA foreign_key_list(t)` |
| Query plan | `EXPLAIN QUERY PLAN <sql>` |
| Bytecode (optional) | `EXPLAIN <sql>` |
| Statistics | SQL aggregates over the data itself (see [STATISTICS.md](STATISTICS.md)) |

Adding another engine means writing another implementation of that interface; the optimizer
itself would not change.

## Safety

- Files are opened **read-only** (`mode=ro`) unless `ALLOW_INDEX_CREATION=true`.
- Only single, read-only `SELECT` statements are accepted, validated on the `sqlglot` AST.
- `PRAGMA query_only` is also set around every execution.
- Table and column names found in the schema are escaped as identifiers, so unusual names
  (spaces, dashes, quotes) work and cannot be used for injection.
- The connection is shared, so every use is serialized with a lock (the server runs endpoints
  on a thread pool, and execution toggles connection-level settings).

## Switching databases

From the UI: click the database chip in the top bar and enter a path. From the API:
`POST /api/database/connect {"path": "..."}`. The path is read by the backend on its own
machine. If the file is missing, not a SQLite database, or unreadable, the request fails with
a clear message and the previous connection stays active.

## Limits

- Statistics are computed on demand with SQL aggregates and cached briefly, so the first
  analysis of a large table scans it.
- SQLite has no `EXPLAIN ANALYZE`; runtime is measured by application-level benchmarking,
  which includes client overhead and is not comparable to the cost model's abstract units.
