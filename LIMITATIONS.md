# Limitations & Future Scope

## Limitations vs PostgreSQL (and in general)

**Statistics**
- No persistent catalog statistics like PostgreSQL's `pg_statistic`/ANALYZE. We compute
  statistics on demand with SQL aggregates and cache them briefly. This is accurate but
  costs a scan the first time.
- Histograms are single-column most-common-values only — no equi-height/quantile
  histograms and no multi-column or cross-column correlation statistics.

**Selectivity & cardinality**
- Predicates are assumed independent (`AND`/`OR`), which over/under-estimates for
  correlated columns.
- Range selectivity assumes a uniform distribution between min and max.
- `LIKE` and any predicate we cannot model precisely fall back to a configured default.

**Cost model**
- It is an **educational abstract model**, not calibrated to any real hardware. The
  constants are tunable but do not correspond to measured page/CPU costs.
- Buffer-cache/warm-cache effects, TOAST, compression, parallelism and concurrency are
  not modelled.

**Plan space**
- Join enumeration considers **left-deep** trees (exhaustive for small queries, System-R
  DP for larger). Bushy plans are not enumerated.
- No subquery/CTE flattening, no semi/anti-join strategies, no window-function planning.
- Aggregate is costed as hash aggregation only; no sort-based grouping variants.

**SQL coverage**
- Supported: `SELECT`, `FROM`, `INNER`/`LEFT` joins, `WHERE`, `GROUP BY`, aggregates,
  `ORDER BY`, aliases, basic expressions. Subqueries, `HAVING`, `UNION`, window
  functions and `LIMIT`-aware costing are out of scope for the core.

**SQLite specifics**
- SQLite has no `EXPLAIN ANALYZE`; runtime is measured by application-level benchmarking,
  which includes client/round-trip overhead and is **not** comparable to optimizer cost.
- `EXPLAIN` bytecode is exposed for inspection but not deeply interpreted.

**AI copilot**
- With OpenAI configured, output quality depends on the model; without it, explanations
  are deterministic templates over the structured data. In both cases the copilot is
  constrained to the supplied optimizer data and may say information is unavailable.

## Deployment & product gaps

- **No authentication** on any endpoint. Uploads are accepted from anyone who can reach the
  server; set `ALLOW_PATH_CONNECT=false` and put it behind your own access control if exposed.
- Only SQLite is supported: no PostgreSQL/MySQL/DuckDB adapters, no remote connections (so no
  SSRF controls exist), and no hosted-deployment hardening.
- No saved-investigation/regression lab, plan-vs-plan diff, or workload CSV import in the
  committed feature set (see [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)).
- Upload validation (header, `quick_check`, read-only open) is not a defence against every
  malicious SQLite file; treat uploads from untrusted users as unsafe.
- The 3D landing scene shows an illustrative sample plan, not data from your database.

## Explicitly out of scope (future scope)

These are intentionally **not** implemented until the core is complete and are recorded
here as future directions:

- Distributed / multi-region query optimization
- Partition advisor
- Lock monitoring and concurrency analysis
- Continuous database health monitoring
- Workload forecasting
- Reinforcement-learning / learned cost models
- Automatic (unattended) index creation and tuning
- PDF / scheduled reporting
- Multi-database (cross-engine) optimization
- Bushy join plans, subquery/CTE optimization, window-function planning
- Equi-height & multi-column histograms, correlation statistics
