"""Create a support ticket."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from assistflow_contracts.support import Ticket, TicketCategory, TicketPriority, TicketStatus
from assistflow_conversations.audit import audit_payload
from assistflow_conversations.repository import AuditEventRecord, AuditRepository
from assistflow_customers.hashing import canonical_hash
from assistflow_customers.repository import (
    CustomerRepository,
    IdempotencyRepository,
    replay_or_conflict,
)
from sqlalchemy.orm import Session

from assistflow_tickets.repository import TicketRecord, TicketRepository

_COMMAND = "create_ticket"


@dataclass(frozen=True)
class TicketWrite:
    ticket: Ticket
    replayed: bool


def create_ticket(
    session: Session,
    tenant_id: UUID,
    customer_id: UUID,
    priority: TicketPriority,
    category: TicketCategory,
    summary: str,
    idempotency_key: str,
    *,
    conversation_id: UUID | None = None,
    correlation_id: str,
    actor_type: str,
    actor_id: UUID,
) -> TicketWrite:
    """Open a ticket for a customer in the same tenant. Replays return the original ticket."""
    arguments_hash = canonical_hash(
        {
            "customer_id": str(customer_id),
            "priority": priority.value,
            "category": category.value,
            "summary": summary,
            "conversation_id": None if conversation_id is None else str(conversation_id),
        }
    )
    idempotency = IdempotencyRepository(session)
    stored = replay_or_conflict(
        idempotency.find(tenant_id, _COMMAND, idempotency_key),
        arguments_hash,
    )
    if stored is not None:
        return TicketWrite(ticket=Ticket.model_validate(stored), replayed=True)

    CustomerRepository(session).require(tenant_id, customer_id)
    created_at = datetime.now(UTC)
    record = TicketRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        customer_id=customer_id,
        conversation_id=conversation_id,
        priority=priority,
        category=category,
        status=TicketStatus.OPEN,
        summary=summary,
        assigned_to=None,
        created_at=created_at,
    )
    TicketRepository(session).insert(record)
    AuditRepository(session).append(
        AuditEventRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="ticket.created",
            target_type="ticket",
            target_id=record.id,
            payload=audit_payload(
                {
                    "ticket_id": str(record.id),
                    "customer_id": str(customer_id),
                    "conversation_id": None if conversation_id is None else str(conversation_id),
                    "category": category.value,
                    "priority": priority.value,
                }
            ),
            created_at=created_at,
        )
    )
    ticket = _public(record)
    idempotency.save(
        record_id=uuid4(),
        tenant_id=tenant_id,
        command_name=_COMMAND,
        idempotency_key=idempotency_key,
        arguments_hash=arguments_hash,
        result_json=cast(dict[str, object], ticket.model_dump(mode="json")),
        created_at=created_at,
    )
    return TicketWrite(ticket=ticket, replayed=False)


def _public(record: TicketRecord) -> Ticket:
    return Ticket(
        id=record.id,
        priority=record.priority,
        category=record.category,
        status=record.status,
        summary=record.summary,
        conversation_id=record.conversation_id,
        created_at=record.created_at,
    )
