"""Hosted publisher. boto3 is imported only when this publisher is constructed."""

from __future__ import annotations

import json
from typing import Any, Protocol

from assistflow_conversations.outbox import DomainEvent


class _EventClient(Protocol):
    def put_events(self, *, Entries: list[dict[str, str]]) -> dict[str, object]:
        """Send one EventBridge entry."""


class _QueueClient(Protocol):
    def send_message(self, *, QueueUrl: str, MessageBody: str) -> dict[str, object]:
        """Send one SQS message."""


class AwsEventPublisher:
    """Publish to EventBridge when a bus name is set, otherwise to SQS."""

    def __init__(self, *, region: str, bus_name: str, queue_url: str) -> None:
        self._bus_name = bus_name
        self._queue_url = queue_url
        self._events: _EventClient | None = None
        self._sqs: _QueueClient | None = None
        if bus_name:
            self._events = _client("events", region)
        elif queue_url:
            self._sqs = _client("sqs", region)
        else:
            raise ValueError("Async workers need an event bus name or a queue URL.")

    def publish(self, event: DomainEvent) -> None:
        body = json.dumps(event.body())
        if self._events is not None:
            self._events.put_events(
                Entries=[
                    {
                        "Source": "assistflow",
                        "DetailType": event.name,
                        "EventBusName": self._bus_name,
                        "Detail": body,
                    }
                ]
            )
            return
        if self._sqs is not None:
            self._sqs.send_message(QueueUrl=self._queue_url, MessageBody=body)


def _client(name: str, region: str) -> Any:
    import boto3  # type: ignore[import-not-found]

    return boto3.client(name, region_name=region)
