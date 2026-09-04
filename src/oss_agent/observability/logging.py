"""Structured logging with automatic secret redaction.

Every log record can carry structured context (workflow_id, agent, state, action,
duration, result, error). Output is either human-readable text or JSON. A
redaction filter scrubs known secret patterns from every message and every string
field before it is emitted — secrets never reach the logs.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Optional

from oss_agent.safety.secrets import redact

_CONFIGURED = False

# Reserved LogRecord attributes we should not treat as structured "extra".
_RESERVED = set(
    logging.makeLogRecord({}).__dict__.keys()
) | {"message", "asctime", "taskName"}


class RedactionFilter(logging.Filter):
    """Scrub secrets from the message and any string extras."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact(record.msg)
            for key, value in list(record.__dict__.items()):
                if key not in _RESERVED and isinstance(value, str):
                    record.__dict__[key] = redact(value)
        except Exception:  # never let logging redaction crash the app
            pass
        return True


def _structured_extras(record: logging.LogRecord) -> dict[str, Any]:
    return {
        k: v
        for k, v in record.__dict__.items()
        if k not in _RESERVED and not k.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(_structured_extras(record))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = _structured_extras(record)
        if extras:
            kv = " ".join(f"{k}={extras[k]}" for k in sorted(extras))
            return f"{base} | {kv}"
        return base


def configure_logging(level: str = "INFO", fmt: str = "text") -> None:
    """Configure the root ``oss_agent`` logger. Idempotent."""
    global _CONFIGURED
    root = logging.getLogger("oss_agent")
    root.setLevel(level.upper())
    root.handlers.clear()
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.addFilter(RedactionFilter())
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            TextFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                          datefmt="%H:%M:%S")
        )
    root.addHandler(handler)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str, **context: Any) -> logging.LoggerAdapter:
    """Return a logger bound to structured ``context``.

    Ensures configuration has happened at least once so library use never emits
    the 'no handlers' warning.
    """
    if not _CONFIGURED:
        configure_logging()
    base = logging.getLogger(f"oss_agent.{name}" if not name.startswith("oss_agent") else name)
    return logging.LoggerAdapter(base, extra={k: v for k, v in context.items() if v is not None})


def bind(logger: logging.LoggerAdapter, **context: Any) -> logging.LoggerAdapter:
    """Return a new adapter with additional bound context."""
    merged = dict(logger.extra or {})
    merged.update({k: v for k, v in context.items() if v is not None})
    return logging.LoggerAdapter(logger.logger, extra=merged)
