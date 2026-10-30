# Implementation status

**Not production-ready.** No authentication; hosted deployment was not set up; the in-memory rate
limiter and request timeout have known limits (below). Treat it as a strong local/team tool.

## Build and test results (final run)

- Backend: `pytest` -> **263 passed, 23 skipped, 0 failed** (baseline: 103). Skips are MySQL/Postgres
  integration tests that need a live server (`MYSQL_TEST_HOST`, `pgserver`).
- Real-engine integration tests were run green against PostgreSQL 16.2 (17), MySQL 8.0.46 (26 incl.
  the HTTP pipeline) and DuckDB 2.0.0 (40). MariaDB is unverified.
- Frontend: `npm run build` passes.
- Browser (`npm run test:e2e`, Playwright + Edge, 13 tests): **11 of 13 passed on the last complete
  run**; the Lab-compare and save-investigation tests failed there on a slow machine (first backend
  responses took ~30 s, so a wait timed out) and each passes when run alone. A retry is configured; a
  clean full run was not confirmed. Ports are overridable with `E2E_API_PORT` / `E2E_WEB_PORT`.
- Workbench was redesigned to match the landing page (charcoal/ivory, signal orange, lime for verified
  results, Fraunces + mono). Checked by screenshot on desktop 1440 and phone 390; no horizontal overflow.
  An axe contrast pass was done on the previous palette, **not re-run on the new one**.

## Completed and verified

- **SQLite upload** with size cap, header + `quick_check` validation, generated filenames, read-only
  open, cleanup, previous connection kept on failure. `ALLOW_PATH_CONNECT=false` blocks path connect.
- **Landing page** (`/`) with a lazy Three.js scroll scene, labelled illustrative sample plan, static
  fallback for reduced motion / no WebGL; workbench at `/app`. Screenshots checked by hand on desktop,
  mobile and reduced motion (see "Known issues").
- **PostgreSQL connector**: introspection, statistics, `EXPLAIN (FORMAT JSON)` (never executes the
  query), benchmarking, read-only transactions, statement timeout. SSRF guard resolves and pins the
  host IP and blocks loopback/private/link-local/metadata ranges unless `ALLOW_PRIVATE_NETWORK=true`.
  Passwords are never stored, logged or returned (tested).
- **Capability flags** per adapter, exposed in `/api/database`.
- **Workload Observatory**: CSV preview/mapping/validation, sqlglot fingerprinting, ranking by total
  recorded time (derived total flagged; count fallback labelled). No invented metrics.
- **Lab / investigations**: baseline vs candidate with repeated runs, estimated cost and measured time
  kept separate, equivalence check, verdict only on non-overlapping ranges; save, export (MD/JSON),
  schema-change detection on reopen.
- **Plan explorer**: minimap, filter, details panel (unavailable fields say so), non-colour cost
  emphasis, plan-vs-plan diff. Checked in a browser for rendering and keyboard selection.
- **Index Lab**: DDL, patterns, trade-offs, labelled "analytical simulation"; create is gated and
  needs a confirmation dialog.
- **Grounded copilot**: offline explanation built only from optimizer fields (tested for no invented
  numbers); external AI is optional, minimized, redacted, and disclosed in every response.
- **Hardening**: redacted JSON logging, body cap, rate limit, timeout, safety rejections for
  `load_extension`, `readfile`, `writefile` and similar (found and fixed).

## Implemented but not fully verified

- **MySQL adapter** (`backend/app/database/mysql_adapter.py`): 14 tests passed against a temporary
  MySQL 8.0.46 server, but it is **not registered or exposed in the UI**, the optimizer pipeline has
  never been run on it, and MariaDB paths are unrun. Do not treat MySQL as supported.
- **PostgreSQL**: not tested with TLS modes, password auth (test server uses trust auth), or other
  versions. The parser/rewriter still use the SQLite dialect, so Postgres-only syntax (`::`, `ILIKE`)
  may fail. Plans are estimated only. `hypopg` support is untested.
- **UI pages not browser-checked beyond the e2e smoke tests**: SQL editor gutter alignment and
  formatting, onboarding, RemoteConnect form, plan diff labels on a real difference, light theme,
  tablet width, screen readers.
- **External AI provider**: tested with a stub only.
- Copy-plan button was not added.

## Known issues

- Landing: at 100% scroll the faded plan slightly overlaps the CTA paragraph; the saved mobile
  screenshot predates the final mobile fix.
- Browser console shows a 404 on page load (probably favicon; unconfirmed).
- Request timeout returns 504 but cannot stop a running sync handler; rate limiter is per process and
  keyed on the direct client IP.
- The index advisor text still says "SQLite has no hypothetical-index facility" on Postgres.
- Schema graph uses a simple grid layout; large schemas will not look tidy.
- Equivalence checking is evidence on the connected data, not a proof.

## Not built

- DuckDB / Turso connectors; MySQL in the UI.
- Authentication, deployment configuration, multi-worker-safe rate limiting.
- Per-operator actual rows/timings (SQLite does not expose them; Postgres uses plain `EXPLAIN`).
- Interleaved A/B benchmark runs (baseline runs fully before candidate; listed as a caveat).
