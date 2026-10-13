# QueryPilot AI — Handoff

**Repo:** https://github.com/Physics0070/dbms-cp (branch `main`)
**Project folder:** `D:\SOHAM ALL\Btech\SY\SEM I\DBMS\CP`
**State at handoff:** commit `01fa7ce` is pushed; 103 backend tests pass; the frontend builds.

## What it is

A SQL query optimizer and performance workbench for **any SQLite database file**. For a
read-only `SELECT` it:

- discovers the schema and computes statistics from the live data;
- costs candidate plans with its own documented cost model and picks the cheapest;
- suggests a reordered query, **verifies it returns the same rows**, benchmarks both, and
  reports faster / slower / no measurable difference;
- compares with SQLite's `EXPLAIN QUERY PLAN`, advises on indexes, and explains the result
  with an optional AI copilot (works offline without a key).

## How to run

```bash
# Backend
cd backend
pip install -r requirements.txt
cp .env.example .env              # optional; defaults work
python -m seed.generate           # creates the demo DB (it is gitignored)
uvicorn app.main:app --port 8000

# Frontend (second terminal)
cd frontend
npm install
npm run dev                       # http://localhost:5173

# Tests
cd backend
pytest -q                         # 103 passing
```

To stop the servers: `pkill -f uvicorn; pkill -f node`, or kill the listeners on ports 8000
and 5173.

Two demo databases can be generated (both are gitignored):

```bash
python -m seed.generate                                   # e-commerce -> optimizer_demo.db
python -m seed.generate --schema library --db library_demo.db   # unrelated schema
```

## Layout

| Path | Role |
|---|---|
| `backend/app/database/` | `DatabaseAdapter` interface, `SqliteAdapter`, runtime database switching |
| `backend/app/optimizer/` | parser, statistics, selectivity, cost model, plans, join order, `rewriter.py`, index advisor, `examples.py`, copilot, `orchestrator.py` (the pipeline) |
| `backend/app/api/routes/` | `database`, `schema`, `optimize`, `index_advisor`, `history` |
| `backend/app/config.py` | every tunable, overridable from `backend/.env` |
| `backend/tests/` | 103 tests, run against two unrelated schemas |
| `frontend/src/pages/Workspace.tsx` | the main page: editor plus 8 result tabs |
| `docs/screenshots/` | README images |

Other docs in the repo root: `README`, `SETUP`, `ARCHITECTURE`, `OPTIMIZER`, `COST_MODEL`,
`STATISTICS`, `DATABASES`, `API`, `DEMO`, `LIMITATIONS`. All are accurate as of this commit.

## Key decisions

- **SQLite only; no Turso.** All Turso/libSQL code and wording was removed. Another engine
  would need its own adapter, `EXPLAIN` parser and statistics source. PostgreSQL was
  deliberately skipped.
- **Read-only by default.** Databases open with `mode=ro`. "Create index" works only with
  `ALLOW_INDEX_CREATION=true`; otherwise the API returns 403.
- **The rewrite is join-order only,** pinned with `CROSS JOIN … ON`. Subquery pushdown was
  removed: it did not change SQLite's plan and measured slower.
- **The estimated gain is measured against the query as written,** not a "no pushdown"
  strawman (that figure is shown separately as a labelled reference). A rewrite needs at
  least `MIN_ESTIMATED_GAIN_PCT` (default 0.5%).
- **Nothing is hardcoded to a schema.** Tests enforce this, and the example queries are
  generated from whatever database is connected.
- **Deterministic planning.** Join enumeration used to depend on Python's hash seed; a test
  now guards against that.
- **The shared connection is locked.** The server runs endpoints on a thread pool; a test
  fails without the lock.

## Honest caveat

Forcing the cost model's join order was often **not** faster on SQLite: in testing, 3 of 5
verified rewrites measured slower, 1 faster, 1 indistinguishable. SQLite's planner is good.
The UI therefore leads with the measured verdict and says "keep your original query" when
the rewrite measures slower. Equivalence is checked on the connected data only — it is
evidence, not a proof for every database.

## Known limitations

- Rewrites are refused for outer joins, subqueries, `LIMIT`, and unresolved columns.
  `HAVING` is not costed and `UNION` is unsupported.
- Plans are estimated only: there are no per-operator actual rows or timings.
- The AI copilot's OpenAI path has never run against the real API (no key was available);
  the offline path is tested.
- Saved history entries from before the refactor show "unavailable" on the SQLite plan tab
  until the query is re-run.
- No authentication on any endpoint.

## Open items

1. **Deployment was not done.** Still undecided: where to host, and whether to lock the
   public version to the demo data. Without that, a public server would let visitors point it
   at any SQLite file on its disk (`POST /api/database/connect`). Also needed: build the demo
   DB at deploy time (`*.db` is gitignored) and add the deployed domain to `CORS_ORIGINS`.
2. **GitHub topics** `turso` and `libsql` are still on the repo and should be removed.
3. Ideas deliberately **not** built, to avoid scope creep: other databases, `HAVING` /
   `IN` / `EXISTS` rewrites, a plan-vs-plan overlay, composite-index suggestions.

## Practical notes

- On the Windows dev machine, a Python heredoc containing `\n` inside a bash command can lose
  its backslashes. Write scripts to a file instead.
- Configuration is overridable by environment variable; see `backend/.env.example` for the
  full list (database path, index gate, OpenAI endpoint/model/temperature/timeout, cost-model
  constants, MCV and plan-search limits, benchmark counts, CORS origins, history path).
- Comparing estimates with measurements is the point of the tool: do not present an estimated
  gain as a measured speedup in demos or write-ups.
