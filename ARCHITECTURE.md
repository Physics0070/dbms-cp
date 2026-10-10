# Architecture

## Layering

```
                         ┌───────────────────────────┐
   React dashboard  ───► │  FastAPI HTTP API (app/api)│
   (frontend/)           └─────────────┬─────────────┘
                                       │
                         ┌─────────────▼─────────────┐
                         │   Orchestrator            │  app/optimizer/orchestrator.py
                         │   (full pipeline wiring)  │
                         └─────────────┬─────────────┘
                                       │
     ┌─────────────────────────────────┼──────────────────────────────────┐
     │                                 │                                   │
┌────▼─────┐  ┌───────────┐  ┌─────────▼─────────┐  ┌────────────┐  ┌──────▼──────┐
│ parser   │  │ statistics│  │ selectivity /     │  │ cost_model │  │ transforms  │
│ (sqlglot)│  │ selectiv. │  │ cardinality       │  │ physical / │  │ index_advis.│
│ RA tree  │  │ providers │  │                   │  │ join_opt   │  │ explain/cop │
└────┬─────┘  └─────┬─────┘  └─────────┬─────────┘  └─────┬──────┘  └──────┬──────┘
     │              │                  │                  │                │
     └──────────────┴──────────────────┴───────┬──────────┴────────────────┘
                                                │
                                   ┌────────────▼────────────┐
                                   │  DatabaseAdapter (ABC)  │  app/database/adapter.py
                                   │  TursoAdapter (impl)    │  app/database/turso_adapter.py
                                   └────────────┬────────────┘
                                                │
                                        Turso / libSQL / SQLite
```

**Key rule:** the optimizer depends only on the `DatabaseAdapter` abstraction. Swapping
databases means writing a new adapter — no optimizer code changes.

## Directory map

```
backend/
  app/
    config.py                 # all tunables from .env (no magic numbers in logic)
    main.py                   # FastAPI app + CORS + /api/health, /api/config
    history_store.py          # JSON-backed query history (app metadata only)
    database/
      adapter.py              # abstract interface + schema/stat value objects
      turso_adapter.py        # libSQL/SQLite implementation (schema, stats, explain, benchmark)
    optimizer/
      safety.py               # read-only AST validation
      relational_algebra.py   # RA nodes + predicate expression model
      parser.py               # sqlglot AST -> RA tree (dynamic column resolution)
      statistics.py           # cached stats provider over the adapter
      selectivity.py          # selectivity engine (methods + assumptions)
      cardinality.py          # cardinality estimator (System-R joins)
      cost_model.py           # explicit, documented cost formulas
      physical_plans.py       # access paths + join algorithms + costing
      join_optimizer.py       # join-order search (exhaustive + DP)
      transformations.py      # predicate/projection pushdown, join reorder
      index_advisor.py        # what-if hypothetical index analysis
      explain_parser.py       # EXPLAIN QUERY PLAN parsing + comparison
      copilot.py              # AI explanation (OpenAI + offline fallback)
      orchestrator.py         # end-to-end pipeline
    api/
      deps.py
      routes/{schema,optimize,index_advisor,history}.py
  seed/generate.py            # deterministic demo-data generator (+ 2nd schema)
  tests/                      # pytest suite (both schemas)

frontend/
  src/
    api.ts                    # typed API client
    store.tsx                 # React context (query, result, theme)
    components/               # ui, PlanFlow (React Flow), CostChart (Recharts)
    pages/                    # 11 dashboard pages
```

## Request lifecycle (POST /api/optimize)

1. `safety.validate_readonly` parses the SQL and rejects anything non-SELECT.
2. `adapter.get_schema()` discovers tables/columns/indexes/foreign keys.
3. `parser.parse_query` builds the relational algebra tree, resolving columns
   against the discovered schema.
4. `CardinalityEstimator` annotates estimated rows per operator.
5. `PhysicalPlanner` builds access paths and join algorithms; `JoinOptimizer`
   enumerates join orders and selects the lowest-cost plan.
6. `LogicalOptimizer` produces before/after trees and quantifies predicate
   pushdown, projection pushdown and join reordering.
7. `adapter.explain_query` + `explain_parser.compare` compare against Turso's plan.
8. Optional `adapter.benchmark_query` measures real execution time.
9. `IndexAdvisor` simulates hypothetical indexes and re-costs.
10. The structured result is returned (and saved to history). The AI copilot can
    later explain it using only this structured payload.

## Design principles

- **No hardcoding** of schema-derived values — everything is computed at request time.
- **Separation of estimate vs measurement** — abstract cost and benchmark milliseconds
  are never mixed.
- **Configurability** — every constant/assumption lives in `config.py` / `.env`.
- **Read-only by default** — the only write path is explicit, confirmed index creation.
