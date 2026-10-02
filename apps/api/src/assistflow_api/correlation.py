"""Accept or assign a correlation id and return it on every response."""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

import structlog
from assistflow_contracts.observe import (
    TraceHop,
    TraceStore,
    bind_metrics,
    bind_trace_store,
    record_hop,
    reset_metrics,
    reset_trace_store,
)
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from assistflow_api.config import ExecutionMode, Settings
from assistflow_api.logging import bind_production_logs, reset_production_logs
from assistflow_api.metrics import InMemoryMetrics

logger = structlog.get_logger("assistflow.trace")

_MAX_LENGTH = 200


class LoggingTraceStore(TraceStore):
    """Store each hop and write a redacted log line for it."""

    def record(self, hop: TraceHop) -> None:
        super().record(hop)
        logger.info(
            "trace_hop",
            hop=hop.hop,
            correlation_id=hop.correlation_id,
            tenant_id=hop.tenant_id,
            conversation_id=hop.conversation_id,
            tool_name=hop.tool_name,
            error_code=hop.error_code,
            latency_ms=hop.latency_ms,
            status=hop.status,
            runtime_trace_id=hop.runtime_trace_id,
        )


class CorrelationMiddleware:
    """Bind the correlation id for the request and stamp the response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        correlation = correlation_from_headers(scope)
        state = scope.setdefault("state", {})
        if not isinstance(state, dict):
            state = {}
            scope["state"] = state
        state["correlation_id"] = correlation
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation)
        started = time.perf_counter()
        status_code = 500
        tokens = _bind_recorders(scope)
        production = bind_production_logs(_production_mode(scope))

        async def send_with_correlation(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"x-correlation-id"
                ]
                headers.append((b"x-correlation-id", correlation.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_correlation)
        finally:
            failure = state.get("failure_code")
            error_code = failure if isinstance(failure, str) and failure.strip() else None
            if error_code is None and status_code >= 400:
                error_code = "http_error"
            record_hop(
                "http",
                correlation_id=correlation,
                latency_ms=_elapsed_ms(started),
                status=str(status_code),
                error_code=error_code,
            )
            _reset_recorders(tokens)
            reset_production_logs(production)
            structlog.contextvars.clear_contextvars()


def correlation_from_headers(scope: Scope) -> str:
    """Use the caller id when it is a short printable token. Otherwise assign one."""
    raw = _header(scope, b"x-correlation-id")
    if raw is None:
        return str(uuid4())
    value = raw.strip()
    if value == "" or len(value) > _MAX_LENGTH:
        return str(uuid4())
    if any(ord(char) < 32 or ord(char) > 126 for char in value):
        return str(uuid4())
    return value


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            text = value.decode("latin-1")
            return text if isinstance(text, str) else None
    return None


def _bind_recorders(scope: Scope) -> tuple[Any, Any] | None:
    app = scope.get("app")
    state = getattr(app, "state", None)
    store = getattr(state, "trace_store", None)
    metrics = getattr(state, "metrics", None)
    if store is None or metrics is None:
        return None
    return bind_trace_store(store), bind_metrics(metrics)


def _reset_recorders(tokens: tuple[Any, Any] | None) -> None:
    if tokens is None:
        return
    reset_trace_store(tokens[0])
    reset_metrics(tokens[1])


def _production_mode(scope: Scope) -> bool:
    app = scope.get("app")
    state = getattr(app, "state", None)
    if getattr(state, "production_logs", False) is True:
        return True
    settings = getattr(state, "settings", None)
    if not isinstance(settings, Settings):
        return False
    return settings.execution_mode is not ExecutionMode.LOCAL


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def metrics_snapshot(metrics: InMemoryMetrics | object) -> dict[str, float]:
    """Read the bound recorder. A foreign object returns the empty name set."""
    snapshot = getattr(metrics, "snapshot", None)
    if not callable(snapshot):
        return {}
    value = snapshot()
    if isinstance(value, dict):
        return {str(key): float(item) for key, item in value.items()}
    return {}
