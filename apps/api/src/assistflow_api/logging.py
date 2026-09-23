"""Structured logging for the API process."""

from __future__ import annotations

import logging

import structlog


def configure_logging() -> None:
    """Configure JSON logs on stdout. Safe to call more than once."""
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
