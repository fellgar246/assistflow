"""CloudWatch publisher. Import this module only when metrics are enabled."""

from __future__ import annotations

from typing import Protocol

import structlog
from assistflow_contracts.observe import METRIC_NAMES

from assistflow_api.metrics import InMemoryMetrics

logger = structlog.get_logger(__name__)

_NAMESPACE = "AssistFlow"
_DIMENSIONS = {"tool": "ToolName", "status": "Status", "tenant_id": "TenantId"}


class MetricClient(Protocol):
    def put_metric_data(self, **kwargs: object) -> object:
        """Publish one sample."""


class CloudWatchMetrics:
    """Write the same samples locally and to CloudWatch."""

    def __init__(self, inner: InMemoryMetrics, client: MetricClient) -> None:
        self._inner = inner
        self._client = client

    def increment(self, name: str, amount: float = 1, **labels: str) -> None:
        self._inner.increment(name, amount, **labels)
        self._publish(name, amount, "Count", labels)
        if name == "conversation_count":
            tenant = labels.get("tenant_id", "")
            self._publish(
                "human_escalation_rate",
                self._inner.escalation_rate(tenant),
                "None",
                {"tenant_id": tenant} if tenant else {},
            )

    def observe(self, name: str, value: float, **labels: str) -> None:
        self._inner.observe(name, value, **labels)
        unit = "Milliseconds" if name == "agent_latency_ms" else "Count"
        self._publish(name, value, unit, labels)

    def record_escalation(self, tenant_id: str) -> None:
        self._inner.record_escalation(tenant_id)
        self._publish(
            "human_escalation_rate",
            self._inner.escalation_rate(tenant_id),
            "None",
            {"tenant_id": tenant_id},
        )

    def snapshot(self) -> dict[str, float]:
        return self._inner.snapshot()

    def _publish(self, name: str, value: float, unit: str, labels: dict[str, str]) -> None:
        if name not in METRIC_NAMES:
            return
        dimensions = [
            {"Name": cloud_name, "Value": labels[key]}
            for key, cloud_name in _DIMENSIONS.items()
            if labels.get(key, "").strip() != ""
        ]
        try:
            self._client.put_metric_data(
                Namespace=_NAMESPACE,
                MetricData=[
                    {
                        "MetricName": name,
                        "Value": float(value),
                        "Unit": unit,
                        "Dimensions": dimensions,
                    }
                ],
            )
        except Exception as exc:
            logger.info("metric_publish_failed", metric=name, error_type=type(exc).__name__)


def cloudwatch_metrics(inner: InMemoryMetrics, region: str) -> CloudWatchMetrics:
    """Build the publisher. boto3 is imported here, not at process start."""
    import boto3  # type: ignore[import-not-found]

    client: MetricClient = boto3.client("cloudwatch", region_name=region)
    return CloudWatchMetrics(inner, client)
