"""In-process trace hops and the metrics port.

This module does not open a network connection or a database.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

METRIC_NAMES: tuple[str, ...] = (
    "conversation_count",
    "agent_turn_count",
    "agent_latency_ms",
    "model_input_tokens",
    "model_output_tokens",
    "tool_call_count",
    "tool_failure_count",
    "approval_requested_count",
    "approval_accepted_count",
    "approval_rejected_count",
    "human_escalation_rate",
    "rag_retrieval_count",
    "grounded_answer_failure_count",
)

HOP_NAMES: frozenset[str] = frozenset(
    {
        "http",
        "conversation",
        "agent",
        "model",
        "retrieval",
        "gateway",
        "tool",
        "command",
    }
)


@dataclass(frozen=True)
class TraceHop:
    """One hop on a correlation id. It stores names and timings, not payloads."""

    correlation_id: str
    hop: str
    latency_ms: int = 0
    tool_name: str | None = None
    error_code: str | None = None
    status: str | None = None
    tenant_id: str | None = None
    conversation_id: str | None = None
    runtime_trace_id: str | None = None


class TraceStore:
    """Hops recorded for the life of the process."""

    def __init__(self) -> None:
        self._hops: list[TraceHop] = []
        self._lock = Lock()

    def record(self, hop: TraceHop) -> None:
        with self._lock:
            self._hops.append(hop)

    def hops(self, correlation_id: str) -> list[TraceHop]:
        with self._lock:
            return [item for item in self._hops if item.correlation_id == correlation_id]


class Metrics(Protocol):
    """Counters and timings. Labels stay bounded to tool, status, and tenant."""

    def increment(self, name: str, amount: float = 1, **labels: str) -> None:
        """Add `amount` to a counter."""

    def observe(self, name: str, value: float, **labels: str) -> None:
        """Record one sample, such as a latency."""

    def record_escalation(self, tenant_id: str) -> None:
        """Count one human escalation and refresh the rate."""

    def snapshot(self) -> dict[str, float]:
        """Return every metric name and its current total."""


class NullMetrics:
    """Discard samples when no recorder is bound."""

    def increment(self, name: str, amount: float = 1, **labels: str) -> None:
        del name, amount, labels

    def observe(self, name: str, value: float, **labels: str) -> None:
        del name, value, labels

    def record_escalation(self, tenant_id: str) -> None:
        del tenant_id

    def snapshot(self) -> dict[str, float]:
        return {name: 0.0 for name in METRIC_NAMES}


_trace_store: ContextVar[TraceStore | None] = ContextVar("assistflow_trace_store", default=None)
_metrics: ContextVar[Metrics | None] = ContextVar("assistflow_metrics", default=None)
_NULL = NullMetrics()


def bind_trace_store(store: TraceStore) -> Token[TraceStore | None]:
    """Attach the store for this request and any thread that copies the context."""
    return _trace_store.set(store)


def reset_trace_store(token: Token[TraceStore | None]) -> None:
    _trace_store.reset(token)


def bind_metrics(metrics: Metrics) -> Token[Metrics | None]:
    return _metrics.set(metrics)


def reset_metrics(token: Token[Metrics | None]) -> None:
    _metrics.reset(token)


def current_metrics() -> Metrics:
    bound = _metrics.get()
    if bound is None:
        return _NULL
    return bound


def record_hop(
    hop: str,
    *,
    correlation_id: str,
    latency_ms: int = 0,
    tool_name: str | None = None,
    error_code: str | None = None,
    status: str | None = None,
    tenant_id: str | None = None,
    conversation_id: str | None = None,
    runtime_trace_id: str | None = None,
) -> None:
    """Append one hop when a store is bound. A missing store is a no-op."""
    store = _trace_store.get()
    if store is None or correlation_id.strip() == "":
        return
    if hop not in HOP_NAMES:
        return
    store.record(
        TraceHop(
            correlation_id=correlation_id,
            hop=hop,
            latency_ms=max(0, latency_ms),
            tool_name=tool_name,
            error_code=error_code,
            status=status,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            runtime_trace_id=runtime_trace_id,
        )
    )
