"""Structured logging setup for EDGAR-X.

All services log JSON via structlog with ISO timestamps and a per-request
correlation id carried through ``contextvars`` so async tasks inherit it.
"""

from __future__ import annotations

import logging
import sys
import uuid

import structlog

_CORRELATION_ID_KEY = "correlation_id"


def configure_logging(level: int = logging.INFO) -> None:
    """Configure structlog to emit JSON logs to stdout.

    Safe to call multiple times; the last call wins.

    Args:
        level: Standard library logging level applied to the root logger.
    """
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        # PrintLogger resolves sys.stdout at creation; disabling the cache makes
        # every log call pick up the current stream (required for re-configuration
        # and captured-output test environments).
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> structlog.types.FilteringBoundLogger:
    """Return a named structlog logger.

    Args:
        name: Logger name, typically ``__name__`` of the calling module.
    """
    return structlog.get_logger(name)


def bind_correlation_id(correlation_id: str | None = None) -> str:
    """Bind a correlation id to the current context and return it.

    Args:
        correlation_id: Explicit id to bind; a UUID4 is generated when omitted.

    Returns:
        The correlation id now bound to the logging context.
    """
    cid = correlation_id or uuid.uuid4().hex
    structlog.contextvars.bind_contextvars(**{_CORRELATION_ID_KEY: cid})
    return cid


def clear_correlation_id() -> None:
    """Remove any bound correlation id from the current logging context."""
    structlog.contextvars.unbind_contextvars(_CORRELATION_ID_KEY)
