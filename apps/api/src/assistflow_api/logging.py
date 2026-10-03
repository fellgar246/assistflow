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
_sample_success: ContextVar[bool] = ContextVar("assistflow_sample_success", default=False)
_SUCCESS_DETAIL = {
    "tool_name",
    "tool_names",
    "latency_ms",
    "tenant_id",
    "conversation_id",
    "runtime_trace_id",
    "assistant_message",
    "input_tokens",
    "output_tokens",
    "steps",
    "error_codes",
}


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


def omit_successful_trace_detail(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Shorten a successful aws-demo trace. Failures keep the correlation id."""
    if not _sample_success.get() or _is_failure(event_dict):
        return event_dict
    for key in list(event_dict):
        if str(key) in _SUCCESS_DETAIL:
            del event_dict[key]
    return event_dict


def _is_failure(event_dict: MutableMapping[str, Any]) -> bool:
    level = str(event_dict.get("level", "")).lower()
    if level in {"error", "critical"}:
        return True
    status = str(event_dict.get("status", "")).lower()
    if status in {"failed", "blocked", "error"}:
        return True
    error_code = event_dict.get("error_code")
    return isinstance(error_code, str) and error_code.strip() != ""


def payloads_suppressed() -> bool:
    """True when log lines must omit raw model documents."""
    return _production_like.get()


def bind_production_logs(enabled: bool) -> Token[bool]:
    """Mark this request as production-like so raw model documents are dropped."""
    return _production_like.set(enabled)


def reset_production_logs(token: Token[bool]) -> None:
    _production_like.reset(token)


def bind_success_sampling(enabled: bool) -> Token[bool]:
    """Drop bulky fields on successful traces. Failures are unchanged."""
    return _sample_success.set(enabled)


def reset_success_sampling(token: Token[bool]) -> None:
    _sample_success.reset(token)


def configure_logging() -> None:
    """Configure JSON logs on stdout. Safe to call more than once."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            drop_secret_keys,
            drop_model_payloads,
            omit_successful_trace_detail,
            redact_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
