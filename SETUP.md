# Setup

## Prerequisites

- Python 3.10+
- Node.js 18+
- (Optional) A Turso database + auth token for remote mode
- (Optional) An OpenAI API key for the AI copilot (works fully offline without it)

## Backend

```bash
cd backend
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env        # then edit as needed
```

### Configure `.env`

```
# Leave TURSO_DATABASE_URL empty to use a local libSQL/SQLite file (recommended for dev):
TURSO_DATABASE_URL=
TURSO_AUTH_TOKEN=
LOCAL_DB_PATH=optimizer_demo.db

# Optional AI copilot:
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini

# Deterministic demo data:
SEED=42
CUSTOMER_COUNT=2000
ORDER_COUNT=8000
PRODUCT_COUNT=500
```

> **libSQL client note:** the backend prefers the `libsql-experimental` Python client
> when installed. If no prebuilt wheel exists for your platform, it transparently falls
> back to the standard-library `sqlite3` driver — libSQL is SQLite-compatible, so the
> optimizer behaves identically. To use remote Turso, install a working `libsql`
> client and set `TURSO_DATABASE_URL` / `TURSO_AUTH_TOKEN`.

### Generate the demo database

```bash
python -m seed.generate                       # uses .env sizes
python -m seed.generate --customers 500 --orders 2000 --products 200
python -m seed.generate --schema library      # the unrelated proof schema
```

### Run the API

```bash
uvicorn app.main:app --reload --port 8000
# Health check:
curl http://localhost:8000/api/health
```

## Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 (proxies /api → :8000)
```

For a production build:

```bash
npm run build && npm run preview
```

## Using a remote Turso database

1. Create a database with the Turso CLI and get its URL + token.
2. Install a working libSQL Python client in the backend venv.
3. Set `TURSO_DATABASE_URL=libsql://<your-db>.turso.io` and `TURSO_AUTH_TOKEN=...`.
4. Seed it (point the seed generator at a local file first, or load your own schema).
5. Start the API — `/api/health` will report `Turso (remote libSQL)`.

## Running tests

```bash
cd backend
pytest -q
```
