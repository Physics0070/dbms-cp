# syntax=docker/dockerfile:1
FROM node:22-alpine AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ ./
COPY --from=web /src/frontend/dist /app/frontend/dist
# Demo database (read-only at runtime) + a writable data dir for uploads and saved investigations.
RUN python -m seed.generate && mkdir -p data \
    && useradd --system --uid 10001 app && chown -R app /app/backend/data
USER app
ENV DATABASE_PATH=/app/backend/optimizer_demo.db \
    HISTORY_PATH=/app/backend/data/query_history.json \
    UPLOAD_DIR=/app/backend/data/uploads \
    ALLOW_PATH_CONNECT=false ALLOW_PRIVATE_NETWORK=false
VOLUME /app/backend/data
EXPOSE 8000
# One worker on purpose: the current-database holder and rate limiter are per process.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
