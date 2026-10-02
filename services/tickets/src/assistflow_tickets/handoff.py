"""Assign a conversation to a person and close it with the linked ticket."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from assistflow_contracts.conversation import ConversationStatus, MessageAuthor, MessageRole
from assistflow_conversations.audit import audit_payload
from assistflow_conversations.commands import (
    ActorContext,
    MessageWrite,
    append_message,
    change_conversation_status,
)
from assistflow_conversations.outbox import CONVERSATION_RESOLVED, enqueue_event
from assistflow_conversations.repository import (
    AuditEventRecord,
    AuditRepository,
    ConversationRecord,
    ConversationRepository,
)
from assistflow_customers.errors import SupportError
from assistflow_customers.hashing import canonical_hash
from assistflow_customers.repository import IdempotencyRepository, replay_or_conflict
from sqlalchemy.orm import Session

from assistflow_tickets.repository import TicketRecord, TicketRepository

_TAKEOVER = "take_over_conversation"
_RESOLVE = "resolve_conversation"
_WAITING = {ConversationStatus.ESCALATED, ConversationStatus.WAITING_APPROVAL}


@dataclass(frozen=True)
class HandoffWrite:
    conversation: ConversationRecord
    replayed: bool


def take_over(
    session: Session,
    tenant_id: UUID,
    conversation_id: UUID,
    agent_id: UUID,
    agent_name: str,
    idempotency_key: str,
    actor: ActorContext,
) -> HandoffWrite:
    """Assign the conversation and its tickets. A repeat for the same person is a no-op."""
    arguments_hash = canonical_hash(
        {"conversation_id": str(conversation_id), "agent_id": str(agent_id)}
    )
    idempotency = IdempotencyRepository(session)
    stored = replay_or_conflict(
        idempotency.find(tenant_id, _TAKEOVER, idempotency_key),
        arguments_hash,
    )
    current = ConversationRepository(session).require(tenant_id, conversation_id)
    if stored is not None or current.assigned_to == agent_id:
        return HandoffWrite(conversation=current, replayed=True)
    if current.status not in _WAITING:
        raise SupportError(
            "invalid_conversation_status",
            "Take over a conversation that is with the support team or waiting for confirmation.",
            409,
        )

    updated_at = datetime.now(UTC)
    assigned = ConversationRepository(session).assign(
        tenant_id, conversation_id, agent_id, updated_at
    )
    for ticket in TicketRepository(session).list_for_conversations(tenant_id, [conversation_id]):
        TicketRepository(session).update(_assigned_ticket(ticket, agent_id))
    first = _first_name(agent_name)
    append_message(
        session,
        tenant_id,
        current.customer_id,
        conversation_id,
        MessageRole.SYSTEM,
        f"{first} joined the conversation",
        f"takeover:{conversation_id}:{agent_id}",
        actor,
        author_type=MessageAuthor.SYSTEM.value,
    )
    _audit(
        session,
        tenant_id,
        actor,
        action="conversation.taken_over",
        target_id=conversation_id,
        created_at=updated_at,
        fields={
            "conversation_id": str(conversation_id),
            "assigned_to": str(agent_id),
        },
    )
    payload: dict[str, object] = {
        "id": str(assigned.id),
        "assigned_to": str(agent_id),
        "status": assigned.status.value,
    }
    idempotency.save(
        record_id=uuid4(),
        tenant_id=tenant_id,
        command_name=_TAKEOVER,
        idempotency_key=idempotency_key,
        arguments_hash=arguments_hash,
        result_json=payload,
        created_at=updated_at,
    )
    return HandoffWrite(conversation=assigned, replayed=False)


def resolve_case(
    session: Session,
    tenant_id: UUID,
    conversation_id: UUID,
    agent_id: UUID,
    idempotency_key: str,
    actor: ActorContext,
) -> HandoffWrite:
    """Close the conversation and every linked ticket. A second call changes nothing."""
    arguments_hash = canonical_hash(
        {"conversation_id": str(conversation_id), "agent_id": str(agent_id)}
    )
    idempotency = IdempotencyRepository(session)
    stored = replay_or_conflict(
        idempotency.find(tenant_id, _RESOLVE, idempotency_key),
        arguments_hash,
    )
    current = ConversationRepository(session).require(tenant_id, conversation_id)
    if stored is not None or current.status is ConversationStatus.RESOLVED:
        return HandoffWrite(conversation=current, replayed=True)
    if current.assigned_to != agent_id:
        raise SupportError(
            "takeover_required",
            "Take over this conversation before resolving it.",
            409,
        )

    updated_at = datetime.now(UTC)
    append_message(
        session,
        tenant_id,
        current.customer_id,
        conversation_id,
        MessageRole.SYSTEM,
        "Conversation resolved",
        f"resolve:{conversation_id}",
        actor,
        author_type=MessageAuthor.SYSTEM.value,
    )
    updated = change_conversation_status(
        session,
        tenant_id,
        conversation_id,
        ConversationStatus.RESOLVED,
        actor,
    )
    tickets = TicketRepository(session)
    for ticket in tickets.list_for_conversations(tenant_id, [conversation_id]):
        if ticket.status.value == "resolved":
            continue
        tickets.update(_resolved_ticket(ticket))
        _audit(
            session,
            tenant_id,
            actor,
            action="ticket.resolved",
            target_id=ticket.id,
            created_at=updated_at,
            fields={"ticket_id": str(ticket.id), "conversation_id": str(conversation_id)},
        )
    _audit(
        session,
        tenant_id,
        actor,
        action="conversation.resolved",
        target_id=conversation_id,
        created_at=updated_at,
        fields={
            "conversation_id": str(conversation_id),
            "from_status": current.status.value,
            "to_status": ConversationStatus.RESOLVED.value,
        },
    )
    idempotency.save(
        record_id=uuid4(),
        tenant_id=tenant_id,
        command_name=_RESOLVE,
        idempotency_key=idempotency_key,
        arguments_hash=arguments_hash,
        result_json=cast(
            dict[str, object],
            {"id": str(updated.id), "status": updated.status.value},
        ),
        created_at=updated_at,
    )
    enqueue_event(
        session,
        tenant_id=tenant_id,
        correlation_id=actor.correlation_id,
        event_name=CONVERSATION_RESOLVED,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        entities={"conversation_id": conversation_id, "customer_id": current.customer_id},
        created_at=updated_at,
    )
    return HandoffWrite(conversation=updated, replayed=False)


def post_human_reply(
    session: Session,
    tenant_id: UUID,
    conversation_id: UUID,
    agent_id: UUID,
    agent_name: str,
    content: str,
    idempotency_key: str,
    actor: ActorContext,
) -> MessageWrite:
    """Store a person-written reply. It does not call a model."""
    current = ConversationRepository(session).require(tenant_id, conversation_id)
    if current.status is ConversationStatus.RESOLVED:
        raise SupportError(
            "conversation_resolved",
            "This conversation is resolved.",
            409,
        )
    if current.assigned_to != agent_id:
        raise SupportError(
            "takeover_required",
            "Take over this conversation before replying.",
            409,
        )
    return append_message(
        session,
        tenant_id,
        current.customer_id,
        conversation_id,
        MessageRole.ASSISTANT,
        content,
        idempotency_key,
        actor,
        author_type=MessageAuthor.SUPPORT_AGENT.value,
        author_name=agent_name,
    )


def _assigned_ticket(ticket: TicketRecord, agent_id: UUID) -> TicketRecord:
    return TicketRecord(
        id=ticket.id,
        tenant_id=ticket.tenant_id,
        customer_id=ticket.customer_id,
        conversation_id=ticket.conversation_id,
        priority=ticket.priority,
        category=ticket.category,
        status=ticket.status,
        summary=ticket.summary,
        assigned_to=agent_id,
        created_at=ticket.created_at,
    )


def _resolved_ticket(ticket: TicketRecord) -> TicketRecord:
    from assistflow_contracts.support import TicketStatus

    return TicketRecord(
        id=ticket.id,
        tenant_id=ticket.tenant_id,
        customer_id=ticket.customer_id,
        conversation_id=ticket.conversation_id,
        priority=ticket.priority,
        category=ticket.category,
        status=TicketStatus.RESOLVED,
        summary=ticket.summary,
        assigned_to=ticket.assigned_to,
        created_at=ticket.created_at,
    )


def _first_name(display_name: str) -> str:
    part = display_name.strip().split(" ", 1)[0]
    return part or "Support"


def _audit(
    session: Session,
    tenant_id: UUID,
    actor: ActorContext,
    *,
    action: str,
    target_id: UUID,
    created_at: datetime,
    fields: dict[str, object],
) -> None:
    AuditRepository(session).append(
        AuditEventRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            correlation_id=actor.correlation_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            action=action,
            target_type="conversation" if action.startswith("conversation.") else "ticket",
            target_id=target_id,
            payload=audit_payload(fields),
            created_at=created_at,
        )
    )
