"""Open a conversation, append messages, and move status. Each write audits in the same session."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from assistflow_contracts.conversation import (
    Conversation,
    ConversationChannel,
    ConversationStatus,
    Message,
    MessageRole,
)
from assistflow_customers.hashing import canonical_hash
from assistflow_customers.repository import (
    CustomerRepository,
    IdempotencyRepository,
    replay_or_conflict,
)
from sqlalchemy.orm import Session

from assistflow_conversations.audit import audit_payload
from assistflow_conversations.repository import (
    AgentTraceRecord,
    AgentTraceRepository,
    AuditEventRecord,
    AuditRepository,
    ConversationRecord,
    ConversationRepository,
    MessageRecord,
    MessageRepository,
)
from assistflow_conversations.status import transition_status

_OPEN = "open_conversation"
_APPEND = "append_message"

# Fixed stored reply. It does not call a model and does not state an order fact.
ACKNOWLEDGEMENT = (
    "Thanks, I saved your message. I have not looked up an order, delivery, return, or refund."
)


@dataclass(frozen=True)
class ActorContext:
    actor_type: str
    actor_id: UUID
    correlation_id: str


@dataclass(frozen=True)
class ConversationWrite:
    conversation: Conversation
    replayed: bool


@dataclass(frozen=True)
class MessageWrite:
    message: Message
    replayed: bool


def open_conversation(
    session: Session,
    tenant_id: UUID,
    customer_id: UUID,
    idempotency_key: str,
    actor: ActorContext,
) -> ConversationWrite:
    """Store a web conversation as open. Replays return the original row."""
    arguments_hash = canonical_hash({"customer_id": str(customer_id), "channel": "web"})
    idempotency = IdempotencyRepository(session)
    stored = replay_or_conflict(
        idempotency.find(tenant_id, _OPEN, idempotency_key),
        arguments_hash,
    )
    if stored is not None:
        return ConversationWrite(conversation=Conversation.model_validate(stored), replayed=True)

    CustomerRepository(session).require(tenant_id, customer_id)
    created_at = datetime.now(UTC)
    record = ConversationRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        customer_id=customer_id,
        channel=ConversationChannel.WEB,
        status=ConversationStatus.OPEN,
        agent_session_id=None,
        created_at=created_at,
        updated_at=created_at,
    )
    ConversationRepository(session).insert(record)
    _audit(
        session,
        tenant_id,
        actor,
        action="conversation.created",
        target_type="conversation",
        target_id=record.id,
        created_at=created_at,
        fields={
            "conversation_id": str(record.id),
            "customer_id": str(customer_id),
            "channel": record.channel.value,
            "status": record.status.value,
        },
    )
    conversation = _public_conversation(record)
    idempotency.save(
        record_id=uuid4(),
        tenant_id=tenant_id,
        command_name=_OPEN,
        idempotency_key=idempotency_key,
        arguments_hash=arguments_hash,
        result_json=cast(dict[str, object], conversation.model_dump(mode="json")),
        created_at=created_at,
    )
    return ConversationWrite(conversation=conversation, replayed=False)


def append_customer_message(
    session: Session,
    tenant_id: UUID,
    customer_id: UUID,
    conversation_id: UUID,
    content: str,
    idempotency_key: str,
    actor: ActorContext,
    *,
    acknowledge: bool = True,
) -> MessageWrite:
    """Store a customer message.

    When acknowledge is true and the thread has no assistant message yet, store
    one fixed acknowledgement. That text does not call a model and does not
    state an order fact. Callers that run the in-process assistant pass
    acknowledge=False and store the assistant reply themselves.
    """
    written = append_message(
        session,
        tenant_id,
        customer_id,
        conversation_id,
        MessageRole.CUSTOMER,
        content,
        idempotency_key,
        actor,
    )
    if written.replayed or not acknowledge:
        return written
    messages = MessageRepository(session)
    if not messages.has_role(tenant_id, conversation_id, MessageRole.ASSISTANT):
        append_message(
            session,
            tenant_id,
            customer_id,
            conversation_id,
            MessageRole.ASSISTANT,
            ACKNOWLEDGEMENT,
            f"acknowledgement:{idempotency_key}",
            actor,
        )
    return written


def append_message(
    session: Session,
    tenant_id: UUID,
    customer_id: UUID,
    conversation_id: UUID,
    role: MessageRole,
    content: str,
    idempotency_key: str,
    actor: ActorContext,
) -> MessageWrite:
    """Append one message in creation order. Used by replay tests for non-customer roles."""
    arguments_hash = canonical_hash(
        {
            "conversation_id": str(conversation_id),
            "role": role.value,
            "content": content,
        }
    )
    idempotency = IdempotencyRepository(session)
    stored = replay_or_conflict(
        idempotency.find(tenant_id, _APPEND, idempotency_key),
        arguments_hash,
    )
    if stored is not None:
        return MessageWrite(message=Message.model_validate(stored), replayed=True)

    ConversationRepository(session).require_for_customer(tenant_id, customer_id, conversation_id)
    created_at = datetime.now(UTC)
    record = MessageRecord(
        id=uuid4(),
        conversation_id=conversation_id,
        role=role,
        content=content,
        created_at=created_at,
    )
    messages = MessageRepository(session)
    messages.insert(tenant_id, record)
    ConversationRepository(session).touch(tenant_id, conversation_id, created_at)
    _audit(
        session,
        tenant_id,
        actor,
        action="message.created",
        target_type="message",
        target_id=record.id,
        created_at=created_at,
        fields={
            "conversation_id": str(conversation_id),
            "message_id": str(record.id),
            "role": role.value,
        },
    )
    message = _public_message(record)
    idempotency.save(
        record_id=uuid4(),
        tenant_id=tenant_id,
        command_name=_APPEND,
        idempotency_key=idempotency_key,
        arguments_hash=arguments_hash,
        result_json=cast(dict[str, object], message.model_dump(mode="json")),
        created_at=created_at,
    )
    return MessageWrite(message=message, replayed=False)


def record_agent_trace(
    session: Session,
    record: AgentTraceRecord,
    actor: ActorContext,
) -> None:
    """Store a trace and audit the id, prompt version, and stop reason.

    The audit payload does not include prompt text or step summaries.
    """
    AgentTraceRepository(session).insert(record)
    _audit(
        session,
        record.tenant_id,
        actor,
        action="agent.trace_recorded",
        target_type="agent_trace",
        target_id=record.id,
        created_at=record.created_at,
        fields={
            "trace_id": str(record.id),
            "conversation_id": str(record.conversation_id),
            "prompt_id": record.prompt_id,
            "prompt_version": record.prompt_version,
            "stop_reason": record.stop_reason,
            "step_count": len(record.steps),
        },
    )


def change_conversation_status(
    session: Session,
    tenant_id: UUID,
    conversation_id: UUID,
    target: ConversationStatus,
    actor: ActorContext,
) -> ConversationRecord:
    """Apply one allowed status move and audit it in this session."""
    repository = ConversationRepository(session)
    current = repository.require(tenant_id, conversation_id)
    transition_status(current.status, target)
    updated_at = datetime.now(UTC)
    updated = ConversationRecord(
        id=current.id,
        tenant_id=current.tenant_id,
        customer_id=current.customer_id,
        channel=current.channel,
        status=target,
        agent_session_id=current.agent_session_id,
        created_at=current.created_at,
        updated_at=updated_at,
    )
    repository.update_status(updated)
    _audit(
        session,
        tenant_id,
        actor,
        action="conversation.status_changed",
        target_type="conversation",
        target_id=conversation_id,
        created_at=updated_at,
        fields={
            "conversation_id": str(conversation_id),
            "from_status": current.status.value,
            "to_status": target.value,
        },
    )
    return updated


def _audit(
    session: Session,
    tenant_id: UUID,
    actor: ActorContext,
    *,
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
            correlation_id=actor.correlation_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            payload=audit_payload(fields),
            created_at=created_at,
        )
    )


def _public_conversation(record: ConversationRecord) -> Conversation:
    return Conversation(
        id=record.id,
        customer_id=record.customer_id,
        channel=record.channel,
        status=record.status,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _public_message(record: MessageRecord) -> Message:
    return Message(
        id=record.id,
        role=record.role,
        content=record.content,
        created_at=record.created_at,
    )
