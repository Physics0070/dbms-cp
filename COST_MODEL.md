# Cost Model

This is an **explicit, educational** cost model, deliberately independent of SQLite's
own planner. It expresses cost in abstract units that combine estimated **I/O** and
**CPU** work (and, where relevant, **memory**). It never copies a cost value from
SQLite/libSQL.

All constants come from configuration (`config.py` / `.env`) — there are no magic
numbers embedded in the logic.

## Constants

| Symbol | Setting | Default | Meaning |
|-------|---------|---------|---------|
| `Cio`  | `COST_IO_PER_PAGE` | 1.0 | cost of touching one page of I/O |
| `Ccpu` | `COST_CPU_PER_ROW` | 0.01 | cost of processing one row in CPU |
| `Cop`  | `COST_CPU_PER_OPERATOR` | 0.0025 | small per-tuple/operator overhead |
| `R`    | `ROWS_PER_PAGE` | 100 | rows assumed to fit on one page |

Helper: `pages(n) = ceil(n / R)`.

Each operator returns a `CostBreakdown(cpu, io, memory)`; `total = cpu + io + memory`.
A node's **cumulative** cost combines its children's cumulative cost with its own self
cost (see joins below).

## Access operators

### Sequential Scan — `seq_scan(N)`
Reads every page and inspects every row of a table with `N` rows.
```
io  = pages(N) * Cio
cpu = N * Ccpu
```

### Index Scan — `index_scan(N, matched)`
B-tree descent proportional to `log2(N)`, then read the matching leaf pages.
```
io  = (log2(max(2,N)) + pages(matched)) * Cio
cpu = matched * Ccpu
```
`matched = N * selectivity(predicate)`, using the selectivity engine.

### Index Probe — `index_probe(N, matched_per_key)`
Cost of a **single** index lookup, used inside an index-nested-loop join.
```
io  = (log2(max(2,N)) + pages(matched_per_key)) * Cio
cpu = matched_per_key * Ccpu
```
where `matched_per_key ≈ N / distinct(join_key)`.

## Row operators

| Operator | CPU | Memory | Notes |
|----------|-----|--------|-------|
| Filter `filter(in)` | `in * Ccpu` | – | apply a predicate to `in` rows |
| Projection `projection(in)` | `in * Cop` | – | cheap; narrows columns |
| Sort `sort(in)` | `in * log2(in) * Ccpu` | `pages(in) * Cio` | comparison sort |
| Aggregate `aggregate(in, g)` | `in * Ccpu` | `pages(g) * Cio` | hash aggregation into `g` groups |
| Output `output(rows)` | `rows * Cop` | – | producing result rows |

## Join operators

Let the left (outer) subtree produce `L` rows with cumulative cost `cum(L)`, and the
right (inner) subtree produce `Ri` rows with cumulative cost `cum(R)`.

### Nested-Loop Join
Inner side is re-scanned once per outer row.
```
self.cpu   = L * Ri * Cop
cumulative = cum(L) + L * cum(R) + self.total
```
Cheap only when the inner input is tiny.

### Index-Nested-Loop Join *(only when the inner join key is indexed)*
Each outer row probes the inner index instead of re-scanning.
```
per_probe  = index_probe(N_inner, N_inner / distinct(join_key))
cumulative = cum(L) + L * per_probe.total
```

### Hash Join *(equi-joins only)*
Build a hash table on the smaller input, probe with the larger.
```
build, probe = sorted([L, Ri])            # build on the smaller
self.cpu     = (build + probe) * Ccpu
self.memory  = pages(build) * Cio         # hash table resident
cumulative   = cum(L) + cum(R) + self.total
```

### Merge Join *(equi-joins only; requires sorted inputs)*
Sort both inputs on the join key, then merge.
```
self.cpu   = (L + Ri) * Ccpu
cumulative = cum(L) + cum(R) + sort(L).total + sort(Ri).total + self.cpu
```

## Join output cardinality (System-R)

For an equi-join `A.a = B.b`:
```
|A ⋈ B| = |A| * |B| / max(distinct(a), distinct(b))
```
For a non-equi join, `DEFAULT_JOIN_SELECTIVITY` is used; a cross join uses selectivity 1.

## Why these shapes?

- I/O dominates scans; CPU dominates comparisons and sorts — the constants let you tune
  the balance to match a target storage/CPU profile.
- Nested-loop's `L * cum(R)` term makes it explode for large inners, which is exactly
  why hash/merge/index-nested-loop win on big equi-joins — and the optimizer discovers
  that purely from cost.
- All inputs (`N`, `matched`, `distinct`, `groups`) come from statistics computed on the
  live database, so plan choice reflects the **actual** data distribution and skew.
