"""Structured logging for the API process."""

from __future__ import annotations

import logging
from collections.abc import MutableMapping
from contextvars import ContextVar, Token
from typing import Any

import structlog

from assistflow_runtime.redaction import redact_data

_SECRET_KEYS = {
    "authorization",
    "cookie",
    "access_token",
    "refresh_token",
    "assistflow_session",
    "token",
    "email",
    "customer_email",
}
_PAYLOAD_KEYS = {
    "model_payload",
    "raw_model_payload",
    "messages",
    "prompt",
    "prompt_text",
    "completion",
    "request_body",
    "response_body",
}
_production_like: ContextVar[bool] = ContextVar("assistflow_production_logs", default=False)


def drop_secret_keys(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Remove credential fields before a log line is written."""
    for key in list(event_dict):
        if str(key).lower() in _SECRET_KEYS:
            del event_dict[key]
    return event_dict


def drop_model_payloads(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Drop raw model documents in a production-like mode."""
    if not _production_like.get():
        return event_dict
    for key in list(event_dict):
        if str(key).lower() in _PAYLOAD_KEYS:
            del event_dict[key]
    return event_dict


def redact_processor(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Redact secret-shaped strings in every log event."""
    redacted = redact_data(dict(event_dict))
    if isinstance(redacted, dict):
        return redacted
    return event_dict


def payloads_suppressed() -> bool:
    """True when log lines must omit raw model documents."""
    return _production_like.get()


def bind_production_logs(enabled: bool) -> Token[bool]:
    """Mark this request as production-like so raw model documents are dropped."""
    return _production_like.set(enabled)


def reset_production_logs(token: Token[bool]) -> None:
    _production_like.reset(token)


def configure_logging() -> None:
    """Configure JSON logs on stdout. Safe to call more than once."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            drop_secret_keys,
            drop_model_payloads,
            redact_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
