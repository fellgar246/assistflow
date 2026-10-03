"""Hosted memory client. boto3 is imported only when a client is constructed."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from assistflow_contracts.memory import MemoryPreference, SessionFacts
from assistflow_customers.repository import CustomerRepository
from pydantic import ValidationError

from assistflow_memory.allowlist import PURPOSES, RETENTION_DAYS, validate_preference
from assistflow_memory.limits import MemoryLimitError
from assistflow_memory.local_session import ORDER_KIND, SHIPMENT_KIND, clean_session_value
from assistflow_runtime.quota import memory_event_allowed, session_window
from assistflow_runtime.redaction import redact_text


class HostedMemoryClient(Protocol):
    """Subset of the hosted memory API used by the adapters."""

    def create_event(self, **kwargs: Any) -> dict[str, Any]:
        """Store one session event."""

    def list_events(self, **kwargs: Any) -> dict[str, Any]:
        """List session events for one actor."""

    def batch_create_memory_records(self, **kwargs: Any) -> dict[str, Any]:
        """Store preference records."""

    def list_memory_records(self, **kwargs: Any) -> dict[str, Any]:
        """List preference records for one actor."""

    def delete_memory_record(self, **kwargs: Any) -> dict[str, Any]:
        """Delete one preference record."""


class AgentCoreSessionMemory:
    """Hosted short-term memory. The application still caps events and age."""

    def __init__(
        self,
        client: HostedMemoryClient,
        memory_id: str,
        max_events: int,
        max_session_minutes: int,
        customers: CustomerRepository | None = None,
    ) -> None:
        if memory_id.strip() == "":
            raise ValueError("A hosted memory id is required.")
        if max_events < 1:
            raise ValueError("MAX_MEMORY_EVENTS_PER_SESSION must be at least 1.")
        self._client = client
        self._memory_id = memory_id
        self._max_events = max_events
        self._ttl = session_window(max_session_minutes)
        self._customers = customers

    def load(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        conversation_id: UUID,
        now: datetime,
    ) -> SessionFacts:
        actor_id = self._actor(tenant_id, customer_id)
        listed = self._client.list_events(
            memoryId=self._memory_id,
            actorId=actor_id,
            sessionId=str(conversation_id),
        )
        order_id: str | None = None
        status: str | None = None
        for event in _events(listed):
            created = _timestamp(event.get("eventTimestamp"))
            if created is None or created + self._ttl <= now:
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            kind = payload.get("kind")
            value = payload.get("value")
            if not isinstance(kind, str) or not isinstance(value, str):
                continue
            if kind == ORDER_KIND:
                order_id = value
            elif kind == SHIPMENT_KIND:
                status = value
        return SessionFacts(last_order_id=order_id, last_shipment_status=status)

    def record(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        conversation_id: UUID,
        kind: str,
        value: str,
        now: datetime,
    ) -> None:
        if kind not in {ORDER_KIND, SHIPMENT_KIND}:
            raise ValueError("Session memory accepts only an order id or a shipment status.")
        cleaned = clean_session_value(kind, redact_text(value).strip())
        if cleaned is None:
            return
        if now.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        actor_id = self._actor(tenant_id, customer_id)
        listed = self._client.list_events(
            memoryId=self._memory_id,
            actorId=actor_id,
            sessionId=str(conversation_id),
        )
        active = 0
        for event in _events(listed):
            created = _timestamp(event.get("eventTimestamp"))
            if created is not None and created + self._ttl > now:
                active += 1
        if not memory_event_allowed(active, self._max_events):
            raise MemoryLimitError(f"Session memory is limited to {self._max_events} events.")
        self._client.create_event(
            memoryId=self._memory_id,
            actorId=actor_id,
            sessionId=str(conversation_id),
            eventTimestamp=now,
            payload={"kind": kind, "value": cleaned},
        )

    def _actor(self, tenant_id: UUID, customer_id: UUID) -> str:
        if self._customers is not None:
            self._customers.require(tenant_id, customer_id)
        return f"{tenant_id}:{customer_id}"


class AgentCorePreferenceMemory:
    """Hosted long-term preferences. The allowlist is applied before the client call."""

    def __init__(
        self,
        client: HostedMemoryClient,
        memory_id: str,
        customers: CustomerRepository | None = None,
    ) -> None:
        if memory_id.strip() == "":
            raise ValueError("A hosted memory id is required.")
        self._client = client
        self._memory_id = memory_id
        self._customers = customers

    def load(self, tenant_id: UUID, customer_id: UUID, now: datetime) -> list[MemoryPreference]:
        actor_id = self._actor(tenant_id, customer_id)
        listed = self._client.list_memory_records(memoryId=self._memory_id, namespace=actor_id)
        found: list[MemoryPreference] = []
        for record in _records(listed):
            preference = _preference(record)
            if preference is None or preference.retention_deadline <= now:
                continue
            found.append(preference)
        return sorted(found, key=lambda item: item.key)

    def remember(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        key: str,
        value: str,
        now: datetime,
    ) -> MemoryPreference:
        if now.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        stored = validate_preference(key, value)
        actor_id = self._actor(tenant_id, customer_id)
        preference = MemoryPreference(
            key=key,
            value=stored,
            purpose=redact_text(PURPOSES[key]),
            retention_deadline=now + timedelta(days=RETENTION_DAYS),
        )
        self._client.batch_create_memory_records(
            memoryId=self._memory_id,
            records=[
                {
                    "namespace": actor_id,
                    "memoryRecordId": f"{actor_id}:{key}",
                    "content": preference.model_dump(mode="json"),
                }
            ],
        )
        return preference

    def delete(self, tenant_id: UUID, customer_id: UUID) -> None:
        actor_id = self._actor(tenant_id, customer_id)
        listed = self._client.list_memory_records(memoryId=self._memory_id, namespace=actor_id)
        for record in _records(listed):
            record_id = record.get("memoryRecordId")
            if isinstance(record_id, str) and record_id:
                self._client.delete_memory_record(
                    memoryId=self._memory_id,
                    memoryRecordId=record_id,
                )

    def _actor(self, tenant_id: UUID, customer_id: UUID) -> str:
        if self._customers is not None:
            self._customers.require(tenant_id, customer_id)
        return f"{tenant_id}:{customer_id}"


def build_hosted_memory_client(region: str) -> HostedMemoryClient:
    """Construct the hosted client. Call this only when a memory flag and the runtime are on."""
    import boto3  # type: ignore[import-not-found]

    client: HostedMemoryClient = boto3.client("bedrock-agentcore", region_name=region)
    return client


def _events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("events")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("memoryRecordSummaries")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _preference(record: dict[str, Any]) -> MemoryPreference | None:
    content = record.get("content")
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None
        content = parsed
    if not isinstance(content, dict):
        return None
    try:
        return MemoryPreference.model_validate(content)
    except ValidationError:
        return None
