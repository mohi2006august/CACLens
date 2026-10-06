"""Structured logging. Every log line carries key/value fields, never bare strings."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog

_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    level = getattr(logging, os.environ.get("CACLENS_LOG_LEVEL", "INFO").upper(), logging.INFO)
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if os.environ.get("CACLENS_LOG_FORMAT", "console") == "json"
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    logging.basicConfig(level=level, stream=sys.stderr, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str) -> Any:
    configure_logging()
    return structlog.get_logger(name)
