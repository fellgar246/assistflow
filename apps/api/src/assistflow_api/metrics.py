"""In-memory metrics. CloudWatch is constructed only when both switches are on."""

from __future__ import annotations

from threading import Lock
from uuid import UUID

from assistflow_contracts.agent import AgentResult
from assistflow_contracts.observe import METRIC_NAMES, Metrics, current_metrics

_LABELS = frozenset({"tool", "status", "tenant_id"})
_STATUSES = frozenset(
    {
        "succeeded",
        "failed",
        "blocked",
        "pending_approval",
        "accepted",
        "rejected",
    }
)
_RETRIEVAL_TOOL = "search_support_policy"


class InMemoryMetrics:
    """Process-local counters. Unknown labels are dropped, not stored."""

    def __init__(self) -> None:
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._samples: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = {}
        self._escalations: dict[str, float] = {}
        self._lock = Lock()

    def increment(self, name: str, amount: float = 1, **labels: str) -> None:
        safe = _labels(labels)
        with self._lock:
            key = (name, safe)
            self._counters[key] = self._counters.get(key, 0.0) + amount

    def observe(self, name: str, value: float, **labels: str) -> None:
        safe = _labels(labels)
        with self._lock:
            self._samples.setdefault((name, safe), []).append(value)

    def record_escalation(self, tenant_id: str) -> None:
        tenant = tenant_id.strip()
        if tenant == "":
            return
        with self._lock:
            self._escalations[tenant] = self._escalations.get(tenant, 0.0) + 1

    def escalation_rate(self, tenant_id: str) -> float:
        with self._lock:
            conversations = self._counters.get(
                ("conversation_count", (("tenant_id", tenant_id),)),
                0.0,
            )
            escalations = self._escalations.get(tenant_id, 0.0)
        if conversations <= 0:
            return 0.0
        return escalations / conversations

    def snapshot(self) -> dict[str, float]:
        totals = {name: 0.0 for name in METRIC_NAMES}
        with self._lock:
            for (name, _labels), value in self._counters.items():
                if name in totals:
                    totals[name] += value
            for (name, _labels), samples in self._samples.items():
                if name in totals and samples:
                    totals[name] += float(sum(samples))
            escalations = float(sum(self._escalations.values()))
        conversations = totals["conversation_count"]
        totals["human_escalation_rate"] = (escalations / conversations) if conversations else 0.0
        return totals


def build_metrics(aws_enabled: bool, metrics_enabled: bool, region: str) -> Metrics:
    """Return memory counters. Import CloudWatch only when both flags are on."""
    memory = InMemoryMetrics()
    if not aws_enabled or not metrics_enabled:
        return memory
    from assistflow_api.cloudwatch_metrics import cloudwatch_metrics

    return cloudwatch_metrics(memory, region)


def record_turn(result: AgentResult, tenant_id: UUID, latency_ms: int) -> None:
    """Move the turn, tool, token, retrieval, and grounding counters."""
    metrics = current_metrics()
    tenant = str(tenant_id)
    metrics.increment("agent_turn_count", tenant_id=tenant)
    metrics.observe("agent_latency_ms", float(latency_ms), tenant_id=tenant)
    metrics.increment("model_input_tokens", float(result.usage.input_tokens), tenant_id=tenant)
    metrics.increment("model_output_tokens", float(result.usage.output_tokens), tenant_id=tenant)
    for tool in result.executed_tools:
        metrics.increment(
            "tool_call_count",
            tool=tool.name,
            status=tool.status,
            tenant_id=tenant,
        )
        if tool.status in {"failed", "blocked"}:
            metrics.increment(
                "tool_failure_count",
                tool=tool.name,
                status=tool.status,
                tenant_id=tenant,
            )
        if tool.name == _RETRIEVAL_TOOL:
            metrics.increment("rag_retrieval_count", tenant_id=tenant)
    if result.grounded_answer_failures:
        metrics.increment(
            "grounded_answer_failure_count",
            float(result.grounded_answer_failures),
            tenant_id=tenant,
        )


def _labels(labels: dict[str, str]) -> tuple[tuple[str, str], ...]:
    kept: list[tuple[str, str]] = []
    for key, value in labels.items():
        if key not in _LABELS:
            continue
        cleaned = value.strip()
        if cleaned == "" or len(cleaned) > 80:
            continue
        if key == "status" and cleaned not in _STATUSES:
            continue
        if key == "tool" and not cleaned.replace("_", "").isalnum():
            continue
        kept.append((key, cleaned))
    return tuple(sorted(kept))
