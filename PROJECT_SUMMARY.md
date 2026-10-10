# AI-Powered Cost-Based SQL Query Optimizer & Database Performance Analyzer
### Project Summary & Handoff Document

A web-based, **schema-agnostic, cost-based SQL query optimizer** and performance
analyzer built entirely on **Turso / libSQL** (SQLite-compatible) — **no PostgreSQL
anywhere**. It parses SQL with `sqlglot`, discovers the live schema dynamically, computes
real statistics, estimates selectivity/cardinality, enumerates candidate physical plans,
costs them with an explicit cost model, selects the cheapest, applies logical
optimizations, compares against SQLite/libSQL `EXPLAIN QUERY PLAN`, benchmarks real
execution time, advises on hypothetical indexes, and explains everything through an AI
copilot — all in a professional React dashboard.

---

## 1. Status — everything works

| Area | Status |
|------|--------|
| Turso/libSQL connection (remote or local file) | ✅ |
| Dynamic schema discovery | ✅ |
| SQL parsing (sqlglot) → relational algebra | ✅ |
| Statistics computed from live data | ✅ |
| Selectivity & cardinality estimation | ✅ |
| Multiple candidate physical plans + cost-based selection | ✅ |
| Predicate / projection pushdown + join reordering | ✅ |
| Turso `EXPLAIN QUERY PLAN` comparison | ✅ |
| Application-level benchmarking | ✅ |
| What-if index advisor | ✅ |
| AI Copilot (OpenAI + offline fallback) | ✅ |
| Query history | ✅ |
| React dashboard (11 pages) — **verified live in browser** | ✅ |
| **48 backend tests passing** | ✅ |
| Documentation (10 files) | ✅ |
| Hardcoding audit (AST + grep) | ✅ clean |

**Live verification example:** the 3-table join ran end-to-end — selected cost `254.33`,
4 candidates, join order `c ⋈ o ⋈ oi`, HashJoin, application-benchmark median `2.34 ms`,
with the React Flow execution tree, node inspector and Recharts candidate chart all
rendering real data.

---

## 2. The data flow

```
Turso/libSQL → Schema Discovery → Statistics → SQL Parser → Relational Algebra
→ Selectivity → Cardinality → Candidate Physical Plans → Cost Model → Best Plan
→ Logical Optimizations → Turso EXPLAIN QUERY PLAN → Application Benchmark
→ Index Advisor → AI Explanation → React Dashboard
```

---

## 3. Tech stack

- **Backend:** Python, FastAPI, sqlglot, libSQL/Turso client (falls back to stdlib
  `sqlite3` locally — libSQL is SQLite-compatible).
- **Frontend:** React, TypeScript, Vite, Tailwind CSS, React Flow, Recharts.
- **Database:** Turso / libSQL.
- **AI:** OpenAI API (optional; fully functional offline).

---

## 4. Repository layout

```
CP/
├── README.md  ARCHITECTURE.md  OPTIMIZER.md  COST_MODEL.md  STATISTICS.md
├── TURSO.md   API.md  SETUP.md  DEMO.md  LIMITATIONS.md  PROJECT_SUMMARY.md
├── .gitignore
├── backend/
│   ├── requirements.txt   .env.example
│   ├── app/
│   │   ├── config.py  main.py  history_store.py
│   │   ├── database/     adapter.py  turso_adapter.py
│   │   ├── optimizer/    safety.py  relational_algebra.py  parser.py
│   │   │                 statistics.py  selectivity.py  cardinality.py
│   │   │                 cost_model.py  physical_plans.py  join_optimizer.py
│   │   │                 transformations.py  index_advisor.py  explain_parser.py
│   │   │                 copilot.py  orchestrator.py
│   │   └── api/          deps.py  routes/{schema,optimize,index_advisor,history}.py
│   ├── seed/generate.py            # deterministic demo data + unrelated 'library' schema
│   └── tests/                      # 48 pytest tests, run on BOTH schemas
└── frontend/
    ├── package.json  vite.config.ts  tailwind.config.js  tsconfig.json
    └── src/
        ├── api.ts  store.tsx  main.tsx  App.tsx  index.css
        ├── components/  ui.tsx  PlanFlow.tsx (React Flow)  CostChart.tsx (Recharts)
        └── pages/       Overview, Optimizer, RelationalAlgebra, ExecutionPlans,
                         CandidatePlans, SchemaExplorer, Statistics, IndexAdvisor,
                         TursoComparison, Copilot, History
```

---

## 5. How to run

**Backend**
```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1   |  macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m seed.generate                 # generate the demo database
uvicorn app.main:app --reload --port 8000
```

**Frontend** (separate terminal)
```bash
cd frontend
npm install
npm run dev                             # http://localhost:5173
```

Open the dashboard → **SQL Optimizer** → **Optimize**.

**Tests**
```bash
cd backend && pytest -q                 # 48 passed
```

---

## 6. The "no hardcoding" guarantee

Nothing schema-derived is hardcoded. The optimizer discovers tables, columns, indexes,
foreign keys and statistics from the live database at request time. This is enforced by:

1. **A full-pipeline test on a second, unrelated schema** (`library`: authors, books,
   members, loans) — optimization, stats, plans, EXPLAIN, benchmark, index advice all
   work unchanged.
2. **An AST-based source audit** asserting no demo table name appears as a string literal
   or identifier anywhere in `app/optimizer/` or `app/database/`.

The 5-table e-commerce database (`customers, orders, order_items, products, categories`)
exists **only** in `seed/generate.py` as demonstration data.

---

## 7. Sample queries

```sql
-- rare value → index scan tends to win
SELECT * FROM orders WHERE status = 'refunded';

-- join + filter + sort (join-order search, hash join)
SELECT c.name, o.total
FROM customers c
JOIN orders o ON o.customer_id = c.customer_id
WHERE o.status = 'completed' AND c.country = 'India'
ORDER BY o.total DESC;

-- three-way join
SELECT c.name, o.total, oi.quantity
FROM customers c
JOIN orders o ON o.customer_id = c.customer_id
JOIN order_items oi ON oi.order_id = o.order_id
WHERE o.status = 'completed';

-- aggregation
SELECT status, COUNT(*) AS n FROM orders GROUP BY status ORDER BY n DESC;
```

---

## 8. Cost model at a glance

Constants (all configurable in `.env`): `Cio` I/O per page, `Ccpu` CPU per row,
`Cop` per-operator overhead, `R` rows per page; `pages(n)=ceil(n/R)`.

| Operator | Cost |
|----------|------|
| Sequential Scan | `io=pages(N)·Cio`, `cpu=N·Ccpu` |
| Index Scan | `io=(log₂N + pages(matched))·Cio`, `cpu=matched·Ccpu` |
| Nested-Loop Join | `cum(L) + L·cum(R) + L·Ri·Cop` |
| Index-Nested-Loop | `cum(L) + L·index_probe` (inner key indexed) |
| Hash Join | `cum(L)+cum(R)+(build+probe)·Ccpu + pages(build)·Cio` |
| Merge Join | `cum(L)+cum(R)+sort(L)+sort(Ri)+(L+Ri)·Ccpu` |
| Sort | `cpu=n·log₂n·Ccpu`, `mem=pages(n)·Cio` |

Join cardinality (System-R): `|A ⋈ B| = |A|·|B| / max(distinct(a), distinct(b))`.
Full derivations in `COST_MODEL.md`.

---

## 9. Two honest notes

- **libSQL client wheel** isn't available for this Python/Windows combo, so locally it
  runs on the SQLite-compatible fallback (identical behavior). Remote Turso works once a
  libSQL client is installed and `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN` are set — see
  `SETUP.md`.
- **AI Copilot** runs in offline-template mode unless `OPENAI_API_KEY` is set; it is fully
  wired for OpenAI and is constrained to the optimizer's structured output either way.

---

## 10. Out of scope (documented future work)

Distributed optimization, partition advisor, lock/health monitoring, workload
forecasting, RL/learned cost models, automatic index creation, PDF reporting,
multi-database optimization, bushy plans, subquery/CTE optimization, multi-column
histograms. See `LIMITATIONS.md`.
```
