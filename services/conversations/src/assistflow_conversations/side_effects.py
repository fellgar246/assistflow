"""Idempotent consumers for notices, audit fan-out, summaries, and evaluation intake.

In-process dispatch and a hosted worker both call `apply_side_effects`.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog
from assistflow_customers.errors import require_tenant_id
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from assistflow_conversations.audit import audit_payload
from assistflow_conversations.models import (
    ConversationSummaryRow,
    EvaluationIntakeRow,
    NotificationEmailRow,
    NotificationRow,
    SideEffectReceiptRow,
)
from assistflow_conversations.outbox import CONVERSATION_RESOLVED, DomainEvent
from assistflow_conversations.repository import (
    AuditEventRecord,
    AuditRepository,
    MessageRepository,
)

logger = structlog.get_logger(__name__)

_NOTICES = {
    "ticket.created": "A support ticket was opened.",
    "conversation.escalated": "A conversation was escalated.",
    "approval.consumed": "A confirmation was applied.",
    "conversation.resolved": "A conversation was resolved.",
}
AUDIT_ACTION = "side_effect.recorded"
_SUMMARY_LIMIT = 500
_PREVIEW_LIMIT = 160


def apply_side_effects(session: Session, event: DomainEvent, *, sample_rate: float) -> None:
    """Run every consumer for one event. A later step can fail without undoing an earlier one."""
    _commit_step(session, lambda: deliver_notification(session, event))
    _commit_step(session, lambda: deliver_audit(session, event))
    if event.name == CONVERSATION_RESOLVED:
        _commit_step(session, lambda: deliver_summary(session, event))
        _commit_step(session, lambda: deliver_evaluation(session, event, sample_rate=sample_rate))


def deliver_notification(session: Session, event: DomainEvent) -> None:
    """Store one in-app notice and one logged email row for this event id."""
    if not _claim(session, "notification", event):
        return
    summary = _NOTICES.get(event.name, "A support update was recorded.")
    created_at = datetime.now(UTC)
    session.add(
        NotificationRow(
            id=uuid4(),
            tenant_id=event.tenant_id,
            event_id=event.event_id,
            event_name=event.name,
            summary=summary,
            conversation_id=_optional_uuid(event.entities.get("conversation_id")),
            ticket_id=_optional_uuid(event.entities.get("ticket_id")),
            created_at=created_at,
        )
    )
    session.add(
        NotificationEmailRow(
            id=uuid4(),
            tenant_id=event.tenant_id,
            event_id=event.event_id,
            body=summary,
            status="logged",
            created_at=created_at,
        )
    )
    logger.info(
        "notification_email_logged",
        event_id=str(event.event_id),
        tenant_id=str(event.tenant_id),
        event_name=event.name,
        channel="email",
    )


def deliver_audit(session: Session, event: DomainEvent) -> None:
    """Append one fan-out audit row. A second delivery of this event id is a no-op."""
    if not _claim(session, "audit", event):
        return
    AuditRepository(session).append(
        AuditEventRecord(
            id=uuid4(),
            tenant_id=event.tenant_id,
            correlation_id=event.correlation_id,
            actor_type=event.actor_type,
            actor_id=event.actor_id,
            action=AUDIT_ACTION,
            target_type="event",
            target_id=event.event_id,
            payload=audit_payload({"event_id": str(event.event_id), "event_name": event.name}),
            created_at=datetime.now(UTC),
        )
    )


def deliver_summary(session: Session, event: DomainEvent) -> None:
    """Store a short summary. Resolve already committed in an earlier transaction."""
    if event.name != CONVERSATION_RESOLVED:
        return
    conversation_id = _required_uuid(event.entities.get("conversation_id"))
    if not _claim(session, "summary", event):
        return
    session.add(
        ConversationSummaryRow(
            id=uuid4(),
            tenant_id=event.tenant_id,
            conversation_id=conversation_id,
            event_id=event.event_id,
            summary=summarize_conversation(session, event.tenant_id, conversation_id),
            created_at=datetime.now(UTC),
        )
    )


def deliver_evaluation(session: Session, event: DomainEvent, *, sample_rate: float) -> None:
    """Mark a resolved conversation when the configured sample rate selects this event id."""
    if event.name != CONVERSATION_RESOLVED:
        return
    if not should_sample(event.event_id, sample_rate):
        return
    conversation_id = _required_uuid(event.entities.get("conversation_id"))
    if not _claim(session, "evaluation", event):
        return
    session.add(
        EvaluationIntakeRow(
            id=uuid4(),
            tenant_id=event.tenant_id,
            conversation_id=conversation_id,
            event_id=event.event_id,
            created_at=datetime.now(UTC),
        )
    )


def summarize_conversation(session: Session, tenant_id: UUID, conversation_id: UUID) -> str:
    """Build a short summary from the transcript length and a clipped customer line."""
    messages = MessageRepository(session).list_all(tenant_id, conversation_id)
    visible = [message for message in messages if message.role.value != "tool"]
    preview = ""
    for message in visible:
        if message.role.value == "customer":
            preview = _preview(message.content)
            break
    base = f"Resolved conversation. {len(visible)} messages."
    if preview == "":
        return base
    return f"{base} {preview}"[:_SUMMARY_LIMIT]


def should_sample(event_id: UUID, rate: float) -> bool:
    """Choose the same way for every delivery of this event id."""
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    bucket = int.from_bytes(event_id.bytes[:2], "big") % 1000
    return bucket < round(rate * 1000)


def list_notifications(session: Session, tenant_id: UUID) -> list[NotificationRow]:
    """Notices for one tenant, oldest first."""
    tenant_id = require_tenant_id(tenant_id)
    rows = session.scalars(
        select(NotificationRow)
        .where(NotificationRow.tenant_id == tenant_id)
        .order_by(NotificationRow.created_at, NotificationRow.id)
    )
    return list(rows)


def _commit_step(session: Session, step: Callable[[], None]) -> None:
    try:
        step()
        session.commit()
    except Exception:
        session.rollback()
        raise


def _claim(session: Session, consumer: str, event: DomainEvent) -> bool:
    require_tenant_id(event.tenant_id)
    existing = session.scalar(
        select(SideEffectReceiptRow.id).where(
            SideEffectReceiptRow.consumer_name == consumer,
            SideEffectReceiptRow.event_id == event.event_id,
        )
    )
    if existing is not None:
        return False
    try:
        with session.begin_nested():
            session.add(
                SideEffectReceiptRow(
                    id=uuid4(),
                    tenant_id=event.tenant_id,
                    consumer_name=consumer,
                    event_id=event.event_id,
                    created_at=datetime.now(UTC),
                )
            )
            session.flush()
    except IntegrityError:
        return False
    return True


def _optional_uuid(value: str | None) -> UUID | None:
    if value is None or value == "":
        return None
    return UUID(value)


def _required_uuid(value: str | None) -> UUID:
    if value is None or value == "":
        raise ValueError("The event is missing a conversation id.")
    return UUID(value)


def _preview(text: str) -> str:
    lowered = text.lower()
    if "bearer " in lowered or "password" in lowered:
        return ""
    collapsed = " ".join(text.split())
    if len(collapsed) <= _PREVIEW_LIMIT:
        return collapsed
    return collapsed[:_PREVIEW_LIMIT]
