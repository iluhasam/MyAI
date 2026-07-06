"""Structured logging setup (stdlib-only, zero external deps for the MVP).

Emits key=value structured lines so logs stay greppable in dev and are trivial
to swap for JSON in prod. ``get_logger`` returns a namespaced child logger.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

_CONFIGURED = False


class _KeyValueFormatter(logging.Formatter):
    """Render standard fields plus any ``extra={...}`` keys as ``k=v`` pairs."""

    _RESERVED = frozenset(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        base = f"{self.formatTime(record)} [{record.levelname:<7}] {record.name}: {record.getMessage()}"
        extras: dict[str, Any] = {
            k: v for k, v in record.__dict__.items() if k not in self._RESERVED
        }
        if extras:
            rendered = " ".join(f"{k}={v!r}" for k, v in extras.items())
            base = f"{base} | {rendered}"
        if record.exc_info:
            base = f"{base}\n{self.formatException(record.exc_info)}"
        return base


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger once. Idempotent across repeated calls."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_KeyValueFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger (e.g. ``get_logger(__name__)``)."""
    return logging.getLogger(name)
