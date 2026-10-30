"""Pure-ASGI hardening: body size cap, request timeout, per-IP rate limit, redacted access log.

Limits are read from settings on every request so they can be changed without a restart in
tests. The timeout answers the client with 504 but cannot kill a synchronous handler that is
already running in the thread pool (ponytail: use a worker process per request if that matters).
"""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import time
from collections import defaultdict, deque

from .config import get_settings
from .logging_setup import redact

log = logging.getLogger("querypilot.http")

_UPLOAD = "/api/database/upload"  # has its own, larger cap
_HEAVY = ("/api/optimize", "/api/copilot", "/api/benchmark", "/api/lab/", "/api/workload/", _UPLOAD)


class _TooLarge(Exception):
    pass


class HardeningMiddleware:
    def __init__(self, app):
        self.app = app
        self._hits: dict[str, deque] = defaultdict(deque)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        cfg = get_settings()
        path = scope["path"]
        started = {"v": False, "status": 0}
        t0 = time.perf_counter()

        async def send_wrap(msg):
            if msg["type"] == "http.response.start":
                started["v"] = True
                started["status"] = msg["status"]
            await send(msg)

        async def reject(status: int, detail: str, headers=()):
            body = json.dumps({"detail": detail}).encode()
            await send_wrap({"type": "http.response.start", "status": status,
                             "headers": [(b"content-type", b"application/json"), *headers]})
            await send_wrap({"type": "http.response.body", "body": body})

        if cfg.api_token and path.startswith("/api/") and path != "/api/health" and scope["method"] != "OPTIONS":
            auth = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
            scheme, _, supplied = auth.partition(" ")
            if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.strip().encode(), cfg.api_token.encode()):
                await reject(401, "Authentication required.", [(b"www-authenticate", b"Bearer")])
                return self._log(scope, started, t0)

        if path.startswith(_HEAVY) and cfg.rate_limit_per_min > 0:
            ip = (scope.get("client") or ("?", 0))[0]
            q, now = self._hits[ip], time.monotonic()
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= cfg.rate_limit_per_min:
                wait = int(60 - (now - q[0])) + 1
                await reject(429, "Too many requests. Try again shortly.", [(b"retry-after", str(wait).encode())])
                return self._log(scope, started, t0)
            q.append(now)

        limit = cfg.max_request_mb * 1024 * 1024
        counted = {"n": 0}
        capped = path != _UPLOAD
        length = dict(scope["headers"]).get(b"content-length")
        if capped and length and length.isdigit() and int(length) > limit:
            await reject(413, f"Request body exceeds the {cfg.max_request_mb} MB limit.")
            return self._log(scope, started, t0)

        async def receive_wrap():
            msg = await receive()
            if capped and msg["type"] == "http.request":
                counted["n"] += len(msg.get("body", b""))
                if counted["n"] > limit:
                    raise _TooLarge
            return msg

        try:
            call = self.app(scope, receive_wrap, send_wrap)
            if cfg.request_timeout_s > 0 and path != _UPLOAD:
                await asyncio.wait_for(call, cfg.request_timeout_s)
            else:
                await call
        except _TooLarge:
            if not started["v"]:
                await reject(413, f"Request body exceeds the {cfg.max_request_mb} MB limit.")
        except asyncio.TimeoutError:
            if not started["v"]:
                await reject(504, f"The request exceeded the {cfg.request_timeout_s:g}s time limit.")
        self._log(scope, started, t0)

    @staticmethod
    def _log(scope, started, t0):
        qs = redact(scope.get("query_string", b"").decode("latin-1"))
        log.info("request", extra={"fields": {
            "method": scope["method"], "path": scope["path"], "query": qs,
            "status": started["status"], "ms": round((time.perf_counter() - t0) * 1000, 1)}})
