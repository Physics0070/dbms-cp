# Statistics & Selectivity

Because SQLite/libSQL does not expose PostgreSQL-style catalog statistics, we compute
our own **from the live data** with plain SQL aggregates. Nothing is hardcoded.

## What is collected (`turso_adapter._compute_statistics`)

For each table:
- `row_count` — `SELECT COUNT(*)`.

For each column (one aggregate pass):
```sql
SELECT COUNT(DISTINCT col),
       SUM(CASE WHEN col IS NULL THEN 1 ELSE 0 END),
       MIN(col), MAX(col)
FROM "table";
```
giving `distinct_count`, `null_count`, `null_fraction = null_count / row_count`,
`min_value`, `max_value`.

For low-cardinality columns (data-driven threshold) a **most-common-values (MCV)**
histogram is built:
```sql
SELECT col, COUNT(*) AS c FROM "table"
WHERE col IS NOT NULL GROUP BY col ORDER BY c DESC LIMIT 10;
```

Identifiers are validated and double-quoted before interpolation, so schema-derived
names cannot cause injection.

Every statistics payload is labelled **"Computed from Turso database"** with a UTC
`collected_at` timestamp, and is cached for `STATS_CACHE_TTL` seconds.

## Selectivity engine (`selectivity.py`)

Every estimate returns `{selectivity, method, assumptions, detail}`.

| Predicate | Method | Formula |
|-----------|--------|---------|
| `col = v` (v in MCV) | MCV histogram | `count(v) / row_count` |
| `col = v` (else) | uniform | `(1 - null_fraction) / distinct_count` |
| `col != v` | inequality | `(1 - null_fraction) - sel(col = v)` |
| `col > v`, `>=` | linear interpolation | `(max - v) / (max - min)` |
| `col < v`, `<=` | linear interpolation | `(v - min) / (max - min)` |
| `col BETWEEN a AND b` | range fraction | `(min(b,max) - max(a,min)) / (max - min)` |
| `col IN (...)` | sum of per-value eq | `Σ sel(col = vᵢ)` |
| `col IS NULL` | null fraction | `null_fraction` |
| `col IS NOT NULL` | null fraction | `1 - null_fraction` |
| `LIKE`, unmodelled | configured default | `DEFAULT_RANGE_SELECTIVITY` |
| `A AND B` | independence | `sel(A) * sel(B)` |
| `A OR B` | independence | `sel(A) + sel(B) - sel(A)·sel(B)` |

Fallbacks (`DEFAULT_EQ_SELECTIVITY`, `DEFAULT_RANGE_SELECTIVITY`,
`DEFAULT_JOIN_SELECTIVITY`) are configuration values, used only when statistics are
unavailable. All results are clamped to `[0, 1]`.

## Cardinality (`cardinality.py`)

- **Scan** → base table `row_count`.
- **Selection** → `input * selectivity(predicate)`.
- **Join** → System-R: `|L| * |R| / max(distinct(a), distinct(b))` for equi-joins
  (`DEFAULT_JOIN_SELECTIVITY` otherwise; outer joins preserve the outer side).
- **Aggregate** → product of group-by columns' distinct counts, capped at input rows
  (scalar aggregate → 1 row).
- **Projection / Sort** → pass-through.

## Skew

The demo generator intentionally introduces power-law skew (see [DEMO.md](DEMO.md)), so
the MCV histogram and distinct counts differ markedly across values — e.g. a common
order status is far more selective-friendly than a rare one. The optimizer discovers all
of this from the data; none of it is written down anywhere.
