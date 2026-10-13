# Optimizer

How a SQL string becomes a chosen physical plan.

## 1. Safety validation (`safety.py`)

The SQL is parsed with `sqlglot` and inspected on the **AST**. Only a single read-only
`SELECT` (optionally with a CTE) is allowed. Any `INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/
TRUNCATE/ATTACH/DETACH/PRAGMA/transaction` node is rejected, plus a token-level keyword
scan (ignoring string literals) as defence in depth. The adapter additionally sets
`PRAGMA query_only = ON` around every execution.

## 2. Parsing to relational algebra (`parser.py`, `relational_algebra.py`)

The `sqlglot` AST is converted into an RA tree of nodes:

- `Scan(table, alias)`
- `Selection(predicate, child)`
- `Projection(columns, child)`
- `Join(left, right, condition, join_type)`
- `Aggregate(group_by, aggregates, child)`
- `Sort(keys, child)`

Columns are resolved dynamically: qualified columns use their alias; unqualified columns
are matched against the **discovered** schema to find their owning table. Predicates are
converted into a typed expression model (`Comparison`, `Between`, `InList`, `NullCheck`,
`Like`, `And`, `Or`), and column-vs-column comparisons across tables are recognised as
**join predicates**.

Canonical (pre-optimization) tree, bottom-up:
`Scan/Join → Selection(WHERE) → Aggregate(GROUP BY) → Projection(SELECT) → Sort(ORDER BY)`.

## 3. Statistics, selectivity, cardinality

See [STATISTICS.md](STATISTICS.md). Every referenced table's statistics are computed
from the live database; selectivity and cardinality are derived from them.

## 4. Physical plan generation (`physical_plans.py`)

For each relation the planner builds **access paths**:
- **Sequential Scan** (+ a Filter for pushed-down local predicates), always available.
- **Index Scan** for each index whose leading column matches a sargable local predicate.

For each join it considers **Nested-Loop**, **Index-Nested-Loop** (only when the inner
join key is indexed), **Hash** and **Merge** joins, costs each, and keeps the cheapest.
Join keys and index availability are discovered from the parsed query and schema — never
hardcoded.

## 5. Join-order search (`join_optimizer.py`)

- A join graph is built from the query's join predicates.
- **≤ 6 relations:** exhaustive enumeration of connected left-deep orders. Each order
  becomes a candidate plan.
- **> 6 relations:** System-R style **dynamic programming** over relation subsets
  (`best[subset]`), preferring connected joins.

Each candidate is fully costed; the lowest cumulative cost wins. The result explains
*why* (cost, join order, methods, margin over the next distinct candidate).

## 6. Logical analysis (`transformations.py`)

Operates on the actual RA tree and quantifies each idea by re-costing:

- **Predicate Pushdown** — push single-table WHERE conjuncts to just above their scan.
- **Join Reordering** — written order vs the cost-based best order.
- **Projection Pushdown** — keep only the columns each downstream operator needs.

The Rewrites tab shows the original and transformed trees with per-transformation cost deltas.
The headline estimate compares the best plan with **your query as written** (written join order,
filters already applied at the scans, which is what a real planner does). A plan with no
pushdown at all is reported separately as a labelled reference, because no engine executes that.

## 7. Engine plan comparison, benchmark, index advice

- `explain_parser.py` parses SQLite's `EXPLAIN QUERY PLAN` and compares scan methods, index
  usage and sorting against our plan (alias-normalised).
- `adapter.benchmark_query` runs warm-up + measured executions and reports min/max/avg/median —
  labelled as an Application Benchmark, never mixed with cost.
- `index_advisor.py` discovers candidate columns from WHERE/JOIN/ORDER BY/GROUP BY, simulates a
  hypothetical index on a **copy** of the schema, re-runs the optimizer, and reports the cost
  delta and affected operator. The index is simulated in our cost model, not by the engine, and
  no index is created unless `ALLOW_INDEX_CREATION=true` and the user confirms.

## 8. Optimized-query reconstruction (`rewriter.py`)

The one thing a rewrite can control is **join order**. SQLite already applies single-table
filters at the scan, so wrapping them in subqueries changes the SQL text but not the plan (and
measured slower in testing); pushdown and projection are reported in the analysis tabs instead
of being emitted.

From the cost-based join order the rewriter re-emits the query with the same tables, filters and
select list, joined in the chosen order. SQLite normally picks its own order and ignores the
written one, so the order is pinned with `CROSS JOIN … ON`, which SQLite treats as fixed. Join
conditions move to the earliest join that has all their tables; everything else stays untouched.

It declines anything that could change results: outer joins, subqueries/CTEs/set operations,
`LIMIT/OFFSET`, unresolved columns. `SELECT *` keeps the written order because it fixes output
column order. The query is reported as **rewritten** only if the cost model estimates a gain above
`MIN_ESTIMATED_GAIN_PCT` against the query as written; otherwise the answer is "already optimal".

A rewrite is never shown on trust. `verify_equivalent` executes both queries and compares the
columns and the multiset of rows (row order is not compared). That is evidence for the connected
data, not a proof for every possible database. Timing only claims "faster/slower" when the measured
min–max ranges do not overlap. Because pinning our order overrides SQLite's own planner, the
measurement can disagree with the estimate — the UI leads with the measurement when it does.

Join enumeration is deterministic (ties resolve to the written order), so results do not vary
between runs or processes.

## 9. AI explanation (`copilot.py`)

The copilot receives only the structured optimizer output and is instructed to use
nothing else. Without an OpenAI key it produces a deterministic explanation from the
same data.
