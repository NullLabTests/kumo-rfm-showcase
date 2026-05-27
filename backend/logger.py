"""Application logging with structured format and per-request timing.

Uses ``contextvars`` to track request ID and start time, yielding log
lines like::

    [a1b2c3d4e5f6] +42ms INFO   svc  → POST /api/predict
    [a1b2c3d4e5f6] +8433ms INFO  svc  ← POST /api/predict → 200 (8433ms)

Supports both stderr and optional file output with rotation.

Usage::

    from logger import log, set_request_id, set_request_start

    set_request_id("abc123")
    set_request_start(time.monotonic())
    log.info("Processing request...")
"""

from __future__ import annotations

import logging
import sys
import time
from contextvars import ContextVar
from pathlib import Path

_request_id: ContextVar[str] = ContextVar("request_id", default="")
_request_start: ContextVar[float] = ContextVar("request_start", default=0.0)
_component: ContextVar[str] = ContextVar("component", default="")


class Formatter(logging.Formatter):
    """Custom formatter that prepends request ID and elapsed time."""

    def format(self, record: logging.LogRecord) -> str:
        rid = _request_id.get()
        elapsed = ""
        if rid:
            start = _request_start.get()
            if start:
                elapsed = f" +{int((time.monotonic() - start) * 1000)}ms"
        comp = _component.get()
        comp_part = f" {comp:4s}" if comp else ""
        prefix = f"[{rid}]{elapsed}{comp_part}" if rid else f"{comp_part}"
        return f"{prefix} {record.levelname:5s}  {record.getMessage()}"


def setup(level: str = "INFO", log_file: str | None = None) -> logging.Logger:
    root = logging.getLogger("kumo")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(Formatter())
    root.addHandler(handler)

    if log_file:
        try:
            from logging.handlers import RotatingFileHandler

            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=3)
            fh.setFormatter(Formatter())
            root.addHandler(fh)
        except OSError as exc:
            root.warning("Could not create log file %s: %s", log_file, exc)

    return root


def set_request_id(rid: str) -> None:
    _request_id.set(rid)


def set_request_start(t: float) -> None:
    _request_start.set(t)


def set_component(name: str) -> None:
    _component.set(name)


from settings import settings

log: logging.Logger = setup(settings.log_level)
