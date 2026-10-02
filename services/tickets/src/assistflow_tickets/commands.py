"""Create a support ticket."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from assistflow_contracts.conversation import ConversationStatus
from assistflow_contracts.support import Ticket, TicketCategory, TicketPriority, TicketStatus
from assistflow_conversations.audit import audit_payload
from assistflow_conversations.repository import (
    AuditEventRecord,
    AuditRepository,
    ConversationRecord,
    ConversationRepository,
)
from assistflow_conversations.status import transition_status
from assistflow_customers.errors import SupportError
from assistflow_customers.hashing import canonical_hash
from assistflow_customers.repository import (
    CustomerRepository,
    IdempotencyRepository,
    replay_or_conflict,
)
from sqlalchemy.orm import Session

from assistflow_tickets.repository import (
    TicketNoteRecord,
    TicketNoteRepository,
    TicketRecord,
    TicketRepository,
)

_COMMAND = "create_ticket"
_NOTE = "add_ticket_note"
_ESCALATION = "request_human_escalation"
NOTE_BODY_LIMIT = 2000
SUMMARY_LIMIT = 500


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


@dataclass(frozen=True)
class NoteWrite:
    id: UUID
    replayed: bool


@dataclass(frozen=True)
class EscalationWrite:
    conversation_id: UUID
    ticket_id: UUID
    status: str
    replayed: bool


def add_ticket_note(
    session: Session,
    tenant_id: UUID,
    ticket_id: UUID,
    body: str,
    idempotency_key: str,
    *,
    customer_id: UUID,
    actor_type: str,
    correlation_id: str,
    actor_id: UUID,
) -> NoteWrite:
    """Append one note. A replay with the same key returns the original note."""
    if len(body) > NOTE_BODY_LIMIT:
        raise SupportError("validation_error", "The note is too long.", 400)
    arguments_hash = canonical_hash({"ticket_id": str(ticket_id), "body": body})
    idempotency = IdempotencyRepository(session)
    stored = replay_or_conflict(
        idempotency.find(tenant_id, _NOTE, idempotency_key),
        arguments_hash,
    )
    if stored is not None:
        return NoteWrite(id=UUID(str(stored["id"])), replayed=True)

    ticket = TicketRepository(session).get(tenant_id, ticket_id)
    if ticket is None or (actor_type == "customer" and ticket.customer_id != customer_id):
        raise SupportError("denied", "That ticket is not available.", 403)

    created_at = datetime.now(UTC)
    record = TicketNoteRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        ticket_id=ticket.id,
        body=body,
        created_at=created_at,
        author_type=_note_author(actor_type),
    )
    TicketNoteRepository(session).insert(record)
    _audit(
        session,
        tenant_id,
        correlation_id=correlation_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action="ticket.note_added",
        target_type="ticket_note",
        target_id=record.id,
        created_at=created_at,
        fields={"ticket_id": str(ticket.id), "note_id": str(record.id)},
    )
    idempotency.save(
        record_id=uuid4(),
        tenant_id=tenant_id,
        command_name=_NOTE,
        idempotency_key=idempotency_key,
        arguments_hash=arguments_hash,
        result_json={"id": str(record.id)},
        created_at=created_at,
    )
    return NoteWrite(id=record.id, replayed=False)


def request_human_escalation(
    session: Session,
    tenant_id: UUID,
    customer_id: UUID,
    conversation_id: UUID,
    reason: str,
    idempotency_key: str,
    *,
    actor_type: str,
    correlation_id: str,
    actor_id: UUID,
) -> EscalationWrite:
    """Mark one conversation escalated and open one ticket. Replays do not repeat that."""
    if len(reason) > SUMMARY_LIMIT:
        raise SupportError("validation_error", "The escalation reason is too long.", 400)
    arguments_hash = canonical_hash({"conversation_id": str(conversation_id), "reason": reason})
    idempotency = IdempotencyRepository(session)
    stored = replay_or_conflict(
        idempotency.find(tenant_id, _ESCALATION, idempotency_key),
        arguments_hash,
    )
    if stored is not None:
        return EscalationWrite(
            conversation_id=UUID(str(stored["conversation_id"])),
            ticket_id=UUID(str(stored["ticket_id"])),
            status=str(stored["status"]),
            replayed=True,
        )

    conversation = ConversationRepository(session).get(tenant_id, conversation_id)
    if conversation is None or (
        actor_type == "customer" and conversation.customer_id != customer_id
    ):
        raise SupportError("denied", "That conversation is not available.", 403)

    CustomerRepository(session).require(tenant_id, conversation.customer_id)
    transition_status(conversation.status, ConversationStatus.ESCALATED)
    created_at = datetime.now(UTC)
    ConversationRepository(session).update_status(
        ConversationRecord(
            id=conversation.id,
            tenant_id=conversation.tenant_id,
            customer_id=conversation.customer_id,
            channel=conversation.channel,
            status=ConversationStatus.ESCALATED,
            agent_session_id=conversation.agent_session_id,
            created_at=conversation.created_at,
            updated_at=created_at,
        )
    )
    ticket = TicketRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        customer_id=conversation.customer_id,
        conversation_id=conversation.id,
        priority=TicketPriority.NORMAL,
        category=TicketCategory.OTHER,
        status=TicketStatus.OPEN,
        summary=reason,
        assigned_to=None,
        created_at=created_at,
    )
    TicketRepository(session).insert(ticket)
    _audit(
        session,
        tenant_id,
        correlation_id=correlation_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action="conversation.escalated",
        target_type="conversation",
        target_id=conversation.id,
        created_at=created_at,
        fields={
            "conversation_id": str(conversation.id),
            "ticket_id": str(ticket.id),
            "status": ConversationStatus.ESCALATED.value,
        },
    )
    result: dict[str, object] = {
        "conversation_id": str(conversation.id),
        "ticket_id": str(ticket.id),
        "status": ConversationStatus.ESCALATED.value,
    }
    idempotency.save(
        record_id=uuid4(),
        tenant_id=tenant_id,
        command_name=_ESCALATION,
        idempotency_key=idempotency_key,
        arguments_hash=arguments_hash,
        result_json=result,
        created_at=created_at,
    )
    return EscalationWrite(
        conversation_id=conversation.id,
        ticket_id=ticket.id,
        status=ConversationStatus.ESCALATED.value,
        replayed=False,
    )


def _note_author(actor_type: str) -> str:
    if actor_type == "system":
        return "system"
    if actor_type == "support_agent":
        return "support"
    return "customer"


def _audit(
    session: Session,
    tenant_id: UUID,
    *,
    correlation_id: str,
    actor_type: str,
    actor_id: UUID,
    action: str,
    target_type: str,
    target_id: UUID,
    created_at: datetime,
    fields: dict[str, object],
) -> None:
    AuditRepository(session).append(
        AuditEventRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload=audit_payload(fields),
            created_at=created_at,
        )
    )


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
