"""Write a domain event in the business transaction. Publishing happens later."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from assistflow_customers.errors import require_tenant_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from assistflow_conversations.models import EventOutboxRow

TICKET_CREATED = "ticket.created"
CONVERSATION_ESCALATED = "conversation.escalated"
APPROVAL_CONSUMED = "approval.consumed"
CONVERSATION_RESOLVED = "conversation.resolved"

EVENT_NAMES = frozenset(
    {
        TICKET_CREATED,
        CONVERSATION_ESCALATED,
        APPROVAL_CONSUMED,
        CONVERSATION_RESOLVED,
    }
)

_ENTITY_KEYS = ("ticket_id", "conversation_id", "customer_id", "approval_id")
_SECRET_MARKERS = ("token", "password", "secret", "authorization", "api_key")
PENDING = "pending"
PUBLISHED = "published"


@dataclass(frozen=True)
class DomainEvent:
    """Identifiers for one side effect. The body has no model payload and no secrets."""

    event_id: UUID
    tenant_id: UUID
    correlation_id: str
    name: str
    actor_type: str
    actor_id: UUID
    entities: dict[str, str]

    def body(self) -> dict[str, str]:
        payload = {
            "event_id": str(self.event_id),
            "tenant_id": str(self.tenant_id),
            "correlation_id": self.correlation_id,
            "event_name": self.name,
            "actor_type": self.actor_type,
            "actor_id": str(self.actor_id),
        }
        payload.update(self.entities)
        return payload


class EventPublisher(Protocol):
    """Accept one event. Implementations must not run consumer work."""

    def publish(self, event: DomainEvent) -> None:
        """Record the event for a later consumer."""


def event_from_body(body: Mapping[str, object]) -> DomainEvent:
    """Read a queue message or an EventBridge envelope back into a domain event."""
    detail, name = _detail(body)
    raw_name = detail.get("event_name", name)
    if not isinstance(raw_name, str) or raw_name not in EVENT_NAMES:
        raise ValueError("Event name is missing.")
    return DomainEvent(
        event_id=_uuid_field(detail, "event_id"),
        tenant_id=_uuid_field(detail, "tenant_id"),
        correlation_id=_text_field(detail, "correlation_id"),
        name=raw_name,
        actor_type=_text_field(detail, "actor_type"),
        actor_id=_uuid_field(detail, "actor_id"),
        entities=entity_ids(_entity_values(detail)),
    )


def _detail(body: Mapping[str, object]) -> tuple[Mapping[str, object], str]:
    if "detail" not in body:
        raw_name = body.get("event_name")
        name = raw_name if isinstance(raw_name, str) else ""
        return body, name
    raw_detail = body["detail"]
    if isinstance(raw_detail, str):
        parsed = json.loads(raw_detail)
        if not isinstance(parsed, dict):
            raise ValueError("Event detail must be an object.")
        detail: Mapping[str, object] = parsed
    elif isinstance(raw_detail, dict):
        detail = raw_detail
    else:
        raise ValueError("Event detail must be an object.")
    raw_name = body.get("detail-type", detail.get("event_name"))
    name = raw_name if isinstance(raw_name, str) else ""
    return detail, name


def _entity_values(detail: Mapping[str, object]) -> dict[str, UUID | None]:
    found: dict[str, UUID | None] = {}
    for key in _ENTITY_KEYS:
        raw = detail.get(key)
        if isinstance(raw, str) and raw != "":
            found[key] = UUID(raw)
    return found


def _uuid_field(detail: Mapping[str, object], key: str) -> UUID:
    raw = detail.get(key)
    if not isinstance(raw, str) or raw == "":
        raise ValueError(f"Event field {key} is missing.")
    return UUID(raw)


def _text_field(detail: Mapping[str, object], key: str) -> str:
    raw = detail.get(key)
    if not isinstance(raw, str) or raw == "":
        raise ValueError(f"Event field {key} is missing.")
    return raw


def entity_ids(entities: Mapping[str, UUID | None]) -> dict[str, str]:
    """Keep known entity ids. Drop secrets and anything else."""
    cleaned: dict[str, str] = {}
    for key, value in entities.items():
        lowered = key.lower()
        if any(marker in lowered for marker in _SECRET_MARKERS):
            continue
        if key not in _ENTITY_KEYS or value is None:
            continue
        cleaned[key] = str(value)
    return cleaned


def enqueue_event(
    session: Session,
    *,
    tenant_id: UUID,
    correlation_id: str,
    event_name: str,
    actor_type: str,
    actor_id: UUID,
    entities: Mapping[str, UUID | None],
    created_at: datetime | None = None,
) -> UUID:
    """Insert one outbox row. The caller commits it with the business write."""
    tenant_id = require_tenant_id(tenant_id)
    if event_name not in EVENT_NAMES:
        raise ValueError(f"Unknown event name: {event_name}")
    event_id = uuid4()
    session.add(
        EventOutboxRow(
            id=event_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            event_name=event_name,
            actor_type=actor_type,
            actor_id=actor_id,
            payload=entity_ids(entities),
            status=PENDING,
            attempts=0,
            created_at=datetime.now(UTC) if created_at is None else created_at,
            published_at=None,
        )
    )
    return event_id


@dataclass(frozen=True)
class OutboxRecord:
    id: UUID
    tenant_id: UUID
    correlation_id: str
    name: str
    actor_type: str
    actor_id: UUID
    entities: dict[str, str]
    status: str
    attempts: int

    def to_event(self) -> DomainEvent:
        return DomainEvent(
            event_id=self.id,
            tenant_id=self.tenant_id,
            correlation_id=self.correlation_id,
            name=self.name,
            actor_type=self.actor_type,
            actor_id=self.actor_id,
            entities=dict(self.entities),
        )


class OutboxRepository:
    """Load unpublished events for the dispatcher. Each row still carries its tenant."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def pending(self, limit: int = 50) -> list[OutboxRecord]:
        rows = self._session.scalars(
            select(EventOutboxRow)
            .where(EventOutboxRow.status == PENDING)
            .order_by(EventOutboxRow.created_at, EventOutboxRow.id)
            .limit(limit)
        )
        return [_record(row) for row in rows]

    def mark_published(self, event_id: UUID, published_at: datetime | None = None) -> None:
        row = self._session.get(EventOutboxRow, event_id)
        if row is None or row.status == PUBLISHED:
            return
        row.status = PUBLISHED
        row.published_at = datetime.now(UTC) if published_at is None else published_at

    def record_failure(self, event_id: UUID) -> None:
        row = self._session.get(EventOutboxRow, event_id)
        if row is None or row.status == PUBLISHED:
            return
        row.attempts += 1


def _record(row: EventOutboxRow) -> OutboxRecord:
    payload = row.payload if isinstance(row.payload, dict) else {}
    entities = {
        key: str(payload[key])
        for key in _ENTITY_KEYS
        if key in payload and isinstance(payload[key], str) and payload[key] != ""
    }
    return OutboxRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        correlation_id=row.correlation_id,
        name=row.event_name,
        actor_type=row.actor_type,
        actor_id=row.actor_id,
        entities=entities,
        status=row.status,
        attempts=row.attempts,
    )
