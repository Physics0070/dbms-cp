"""Structured JSON logging with secret redaction."""
from __future__ import annotations

import json
import logging
import re
import sys
import time

_KEYED = re.compile(
    r"""(?ix)\b(password|passwd|pwd|secret|token|api[_-]?key|authorization|x-api-key)(["']?\s*[:=]\s*)(bearer\s+)?(["']?)[^\s"',;&)}]+"""
)
_URL_CREDS = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@:]*:?[^\s/@]*@")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{6,}")
_SK = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}")


def redact(text: str) -> str:
    text = _URL_CREDS.sub(r"\1***@", text)
    text = _KEYED.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(4)}***", text)
    text = _BEARER.sub("Bearer ***", text)
    return _SK.sub("sk-***", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        doc = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            doc.update({k: redact(v) if isinstance(v, str) else v for k, v in extra.items()})
        if record.exc_info:
            doc["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(doc, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger("querypilot")
    root.setLevel(level.upper())
    if not any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(JsonFormatter())
        root.addHandler(h)
    root.propagate = False
