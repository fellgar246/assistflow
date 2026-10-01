"""Structured logging for the API process."""

from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any

import structlog

from assistflow_runtime.redaction import redact_data


def redact_processor(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Redact secret-shaped strings in every log event."""
    redacted = redact_data(dict(event_dict))
    if isinstance(redacted, dict):
        return redacted
    return event_dict


def configure_logging() -> None:
    """Configure JSON logs on stdout. Safe to call more than once."""
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
