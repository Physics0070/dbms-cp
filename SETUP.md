# Setup

## Prerequisites

- Python 3.10+
- Node.js 18+
- Optional: an OpenAI API key for the AI copilot (everything else works without one)

## Backend

```bash
cd backend
python -m venv .venv
# Windows PowerShell:  .venv\Scripts\Activate.ps1
# macOS/Linux:         source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env        # then edit as needed
```

### Generate the demo data (optional)

```bash
python -m seed.generate                       # e-commerce demo, sizes from .env
python -m seed.generate --customers 500 --orders 2000 --products 200
python -m seed.generate --schema library --db library_demo.db   # an unrelated schema
```

You can skip this and point the app at your own SQLite file instead.

### Choose a database

By default the backend opens `optimizer_demo.db`. To start on another file:

```
# backend/.env
DATABASE_PATH=C:\data\my_database.db
```

You can also switch files at runtime from the database chip in the top bar, or with
`POST /api/database/connect`. If the configured file is missing, the backend still starts and
reports "No database connected" until you open one.

### Upload a database

The top-bar database chip also accepts a SQLite file upload (`POST /api/database/upload`, raw
body). Uploads are stored in `UPLOAD_DIR` (default `backend/data/uploads`, not served
statically) under generated names, limited to `MAX_UPLOAD_MB`, validated, opened read-only, and
earlier uploads are deleted once replaced. A failed upload leaves the current connection alone.

```
# backend/.env
UPLOAD_DIR=                # empty -> backend/data/uploads
MAX_UPLOAD_MB=100
ALLOW_PATH_CONNECT=true    # set false on any shared/hosted server
```

`ALLOW_PATH_CONNECT=false` makes `POST /api/database/connect` return 403, so visitors cannot
open arbitrary files on the server disk; uploads and `DATABASE_PATH` still work.

### Read-only by default

Databases are opened **read-only**, so analysing a database can never change it. The
"Create index" action in the Index advisor is disabled unless you set:

```
ALLOW_INDEX_CREATION=true
```

and restart. Everything else (optimization, benchmarking, verification) is read-only either way.

### Run the API

```bash
uvicorn app.main:app --reload --port 8000
curl http://localhost:8000/api/health
```

## Frontend

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173 (proxies /api to :8000)
```

Routes: `/` is the landing page (lazy-loaded Three.js scene, with a static fallback for
reduced motion or no WebGL); the workbench is at `/app` (`/app/schema`, `/app/statistics`,
`/app/history`).

Production build: `npm run build && npm run preview`.

## Tests

```bash
cd backend
pytest -q
```

## Optional: AI copilot

Set `OPENAI_API_KEY` (and optionally `OPENAI_MODEL`) in `backend/.env`. The copilot receives
only the optimizer's structured output for the current query — including the SQL text — and
is instructed not to invent metrics. Without a key it produces a deterministic explanation
from the same data, and nothing leaves your machine.
