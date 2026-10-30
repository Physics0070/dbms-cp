# Implementation plan

## Architecture as found (commit f39614f)

- **Backend** (FastAPI, Python): `DatabaseAdapter` interface with a single `SqliteAdapter`
  (read-only `mode=ro`, locked shared connection); `sqlglot` parser into a relational-algebra
  tree; statistics from live SQL aggregates; documented cost model; left-deep join enumeration
  (exhaustive or System-R DP); join-order rewriter with row-equivalence check and benchmarking;
  `EXPLAIN QUERY PLAN` comparison; index advisor; optional OpenAI copilot with deterministic
  offline fallback; JSON history store.
- **Frontend** (React, Vite, Tailwind, React Flow, Recharts): Workspace page with result tabs,
  Schema, Statistics and History pages, a top-bar database switcher (path entry only).
- **Not present:** other engines, uploads, landing page, workload analysis, saved
  investigations, authentication.

## Baseline (before any change)

- Backend: `pytest -q` -> 103 passed.
- Frontend: `npm run build` -> succeeded (one chunk-size warning).

## Priorities and sequence

1. Real, safe SQLite upload (the only connector the optimizer is validated against).
2. Gate path-based connect for hosted use (`ALLOW_PATH_CONNECT`).
3. Landing page with a scroll-driven Three.js scene, lazy-loaded, with a static fallback.
4. Documentation that states what is and is not built.
5. Remaining requested areas (other engines, benchmark lab, workloads, schema graph, history
   exports, AI grounding) are deferred; see IMPLEMENTATION_STATUS.md.

## Trade-offs

- Upload takes the **raw request body** plus `X-Filename`, avoiding a multipart dependency.
- Plain `three` and scroll-progress easing instead of R3F/GSAP: fewer dependencies, enough for
  one scene.
- The scene is illustrative only and labelled as such; it shows no costs or timings.
- Other engines were not stubbed: exposing a connector that does not work would be fake support.
