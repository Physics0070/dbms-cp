# Deployment

QueryPilot is built for local or small-team use. Read the limits below before exposing it.

## Authentication is a single shared token

Set `API_TOKEN` and every `/api/*` request except `/api/health` must send
`Authorization: Bearer <token>` (constant-time comparison; the token is never logged). The UI asks for
the token once per browser tab and keeps it in `sessionStorage` only.

This is **one shared secret, not user accounts**: no per-user identity, roles, audit trail or
revocation other than changing the token. If `API_TOKEN` is unset the API is open (fine on localhost).

## Required settings for any hosted instance

| Setting | Value | Why |
|---|---|---|
| `API_TOKEN` | long random string | otherwise anyone can use the API |
| `ALLOW_PATH_CONNECT` | `false` | otherwise visitors can open any SQLite file on the server by path |
| `ALLOW_PRIVATE_NETWORK` | `false` | blocks remote-database targets in private/loopback/metadata ranges (SSRF) |
| `RATE_LIMIT_PER_MIN` | e.g. `60` | per-IP limit on heavy endpoints |
| `CORS_ORIGINS` | your origin | the UI is served from the same origin, so keep this tight |

Also:

- **Run one worker.** The rate limiter and the current-database holder are per process, and the
  current database is global, so every user of one server shares the same connected database.
- **Terminate TLS at a reverse proxy** (Caddy, nginx, a cloud load balancer). The bearer token and any
  database password travel in requests. The rate limiter keys on the direct client IP, so behind a
  proxy it sees the proxy's address.
- Use **read-only database credentials** for remote engines.
- Persist `backend/data` (uploads, saved investigations, history) on a volume.

## Production serving

When `frontend/dist` exists the API server also serves the built UI, with a fallback to `index.html`
for `/app/*` routes. `/api/*` is never shadowed. Disable with `SERVE_FRONTEND=false`; point at another
build with `FRONTEND_DIST`.

```bash
cd frontend && npm ci && npm run build
cd ../backend && pip install -r requirements.txt && python -m seed.generate
API_TOKEN=... ALLOW_PATH_CONNECT=false uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

## Docker

```bash
API_TOKEN=change-me docker compose up --build   # http://localhost:8000
```

The multi-stage `Dockerfile` builds the UI, installs the backend, seeds the demo database, runs as a
non-root user, and exposes `/app/backend/data` as a volume.

**Status:** the Dockerfile and compose file are **unbuilt and untested**. The Docker daemon was not
running when they were written. The same production path (token auth, SPA fallback, built `dist`) was
verified in-process and by `backend/tests/test_auth.py`, not inside a container.

## Not provided

User accounts, SSO, multi-tenant isolation (one connected database per server), distributed rate
limiting, secrets management, backups.
