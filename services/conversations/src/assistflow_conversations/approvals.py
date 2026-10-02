"""Store a sensitive proposal and move it only from a customer decision.

Confirm loads the arguments saved here. The caller does not pass a new payload.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from assistflow_contracts.approval import ApprovalStatus, ProposedChange
from assistflow_contracts.conversation import ConversationStatus
from assistflow_contracts.gateway import arguments_hash
from assistflow_customers.errors import SupportError
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from assistflow_conversations.commands import (
    ActorContext,
    change_conversation_status,
    record_tool_execution,
)
from assistflow_conversations.outbox import APPROVAL_CONSUMED, enqueue_event
from assistflow_conversations.repository import (
    ApprovalRecord,
    ApprovalRepository,
    AuditEventRecord,
    AuditRepository,
    ConversationRepository,
    ToolExecutionRecord,
    ToolExecutionRepository,
)

APPROVAL_TTL = timedelta(minutes=15)

_CHANGE: TypeAdapter[ProposedChange] = TypeAdapter(ProposedChange)


@dataclass(frozen=True)
class StoredProposal:
    approval: ApprovalRecord
    execution: ToolExecutionRecord
    reused: bool


@dataclass(frozen=True)
class ApprovalFailure:
    """A decision that must be returned without rolling back the status write."""

    status_code: int
    code: str
    message: str


def store_proposal(
    session: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    actor: ActorContext,
    tool_name: str,
    arguments: dict[str, Any],
    proposed_change: dict[str, Any],
    summary: str,
    now: datetime | None = None,
) -> StoredProposal:
    """Write the approval and its tool row together. Eligible proposals wait."""
    requested_at = datetime.now(UTC) if now is None else now
    key = arguments.get("idempotency_key")
    if not isinstance(key, str) or key.strip() == "":
        raise SupportError("invalid_request", "The proposal is missing a confirmation key.", 400)
    try:
        _CHANGE.validate_python(proposed_change)
    except ValidationError as exc:
        raise SupportError("invalid_request", "The proposal could not be shown.", 400) from exc
    digest = arguments_hash(tool_name, arguments)
    repository = ApprovalRepository(session)
    existing = repository.find_by_key(tenant_id, key)
    if existing is not None:
        if existing.arguments_hash != digest or existing.conversation_id != conversation_id:
            raise SupportError(
                "idempotency_conflict",
                "This confirmation key was already used for a different change.",
                409,
            )
        _wait(session, tenant_id, conversation_id, actor)
        execution = ToolExecutionRepository(session).get(tenant_id, existing.tool_execution_id)
        if execution is None:
            raise SupportError("tool_execution_not_found", "That tool call was not found.", 404)
        return StoredProposal(approval=existing, execution=execution, reused=True)

    execution_id = uuid4()
    approval_id = uuid4()
    execution = ToolExecutionRecord(
        id=execution_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        correlation_id=actor.correlation_id,
        assistant_message_id=None,
        tool_name=tool_name,
        arguments_hash=digest,
        status="pending_approval",
        risk_level="tier2",
        approval_id=approval_id,
        started_at=requested_at,
        finished_at=None,
        result_summary=summary[:240],
    )
    record_tool_execution(session, execution, actor)
    session.flush()
    approval = ApprovalRecord(
        id=approval_id,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        tool_execution_id=execution_id,
        assistant_message_id=None,
        action_type=tool_name,
        proposed_change=dict(proposed_change),
        arguments=dict(arguments),
        arguments_hash=digest,
        status=ApprovalStatus.PENDING,
        requested_at=requested_at,
        approved_at=None,
        approved_by=None,
        expires_at=requested_at + APPROVAL_TTL,
        idempotency_key=key,
    )
    repository.insert(approval)
    _audit(
        session,
        tenant_id,
        actor,
        action="approval.requested",
        approval_id=approval.id,
        created_at=requested_at,
        fields={
            "action_type": tool_name,
            "arguments_hash": digest,
            "status": ApprovalStatus.PENDING.value,
            "conversation_id": str(conversation_id),
        },
    )
    _wait(session, tenant_id, conversation_id, actor)
    return StoredProposal(approval=approval, execution=execution, reused=False)


def expire_elapsed(
    session: Session,
    tenant_id: UUID,
    conversation_id: UUID,
    actor: ActorContext,
    *,
    now: datetime | None = None,
) -> list[ApprovalRecord]:
    """Mark pending rows past their expiry. Reading them is enough to expire them."""
    current = datetime.now(UTC) if now is None else now
    repository = ApprovalRepository(session)
    visible: list[ApprovalRecord] = []
    changed = False
    for record in repository.list_for_conversation(tenant_id, conversation_id):
        if record.status is ApprovalStatus.PENDING and record.expires_at <= current:
            updated = repository.save_status(record, status=ApprovalStatus.EXPIRED)
            _audit(
                session,
                tenant_id,
                _system(actor),
                action="approval.expired",
                approval_id=record.id,
                created_at=current,
                fields={
                    "action_type": record.action_type,
                    "arguments_hash": record.arguments_hash,
                    "status": ApprovalStatus.EXPIRED.value,
                },
            )
            _finish_execution(
                session,
                tenant_id,
                record.tool_execution_id,
                status="blocked",
                summary="This request expired and nothing changed.",
                finished_at=current,
            )
            visible.append(updated)
            changed = True
        else:
            visible.append(record)
    if changed:
        _reopen_if_idle(session, tenant_id, conversation_id, actor, visible)
    return visible


def reject_approval(
    session: Session,
    tenant_id: UUID,
    customer_id: UUID,
    conversation_id: UUID,
    approval_id: UUID,
    actor: ActorContext,
    *,
    now: datetime | None = None,
) -> ApprovalRecord | ApprovalFailure:
    """Cancel a pending proposal. The business rows stay as they were."""
    current = datetime.now(UTC) if now is None else now
    _owned(session, tenant_id, customer_id, conversation_id)
    expire_elapsed(session, tenant_id, conversation_id, actor, now=current)
    record = ApprovalRepository(session).require_for_conversation(
        tenant_id, conversation_id, approval_id
    )
    if record.status is ApprovalStatus.REJECTED:
        return record
    if record.status is not ApprovalStatus.PENDING:
        return ApprovalFailure(
            409,
            "approval_not_pending",
            "This change is no longer waiting for confirmation.",
        )
    updated = ApprovalRepository(session).save_status(record, status=ApprovalStatus.REJECTED)
    _audit(
        session,
        tenant_id,
        actor,
        action="approval.rejected",
        approval_id=record.id,
        created_at=current,
        fields={
            "action_type": record.action_type,
            "arguments_hash": record.arguments_hash,
            "status": ApprovalStatus.REJECTED.value,
        },
    )
    _finish_execution(
        session,
        tenant_id,
        record.tool_execution_id,
        status="blocked",
        summary="You cancelled this change. Nothing was updated.",
        finished_at=current,
    )
    remaining = ApprovalRepository(session).list_for_conversation(tenant_id, conversation_id)
    _reopen_if_idle(session, tenant_id, conversation_id, actor, remaining)
    return updated


def begin_confirm(
    session: Session,
    tenant_id: UUID,
    customer_id: UUID,
    conversation_id: UUID,
    approval_id: UUID,
    actor: ActorContext,
    *,
    now: datetime | None = None,
) -> ApprovalRecord | ApprovalFailure:
    """Load the stored proposal. Expired rows are marked and the write does not run."""
    current = datetime.now(UTC) if now is None else now
    _owned(session, tenant_id, customer_id, conversation_id)
    expire_elapsed(session, tenant_id, conversation_id, actor, now=current)
    record = ApprovalRepository(session).require_for_conversation(
        tenant_id, conversation_id, approval_id
    )
    if record.status is ApprovalStatus.CONSUMED:
        return record
    if record.status is ApprovalStatus.EXPIRED:
        return ApprovalFailure(
            409,
            "approval_expired",
            "This request expired and nothing changed.",
        )
    if record.status is not ApprovalStatus.PENDING:
        return ApprovalFailure(
            409,
            "approval_not_pending",
            "This change is no longer waiting for confirmation.",
        )
    digest = arguments_hash(record.action_type, record.arguments)
    if digest != record.arguments_hash:
        return ApprovalFailure(
            409,
            "approval_hash_mismatch",
            "This confirmation does not match the proposed change.",
        )
    return record


def consume_approval(
    session: Session,
    tenant_id: UUID,
    conversation_id: UUID,
    record: ApprovalRecord,
    actor: ActorContext,
    *,
    now: datetime | None = None,
) -> ApprovalRecord:
    """Mark the approval consumed after the business write in this same session."""
    current = datetime.now(UTC) if now is None else now
    if record.status is ApprovalStatus.CONSUMED:
        return record
    updated = ApprovalRepository(session).save_status(
        record,
        status=ApprovalStatus.CONSUMED,
        approved_at=current,
        approved_by=actor.actor_id,
    )
    _audit(
        session,
        tenant_id,
        actor,
        action="approval.approved",
        approval_id=record.id,
        created_at=current,
        fields={
            "action_type": record.action_type,
            "arguments_hash": record.arguments_hash,
            "status": ApprovalStatus.APPROVED.value,
        },
    )
    _audit(
        session,
        tenant_id,
        actor,
        action="approval.consumed",
        approval_id=record.id,
        created_at=current,
        fields={
            "action_type": record.action_type,
            "arguments_hash": record.arguments_hash,
            "status": ApprovalStatus.CONSUMED.value,
        },
    )
    _finish_execution(
        session,
        tenant_id,
        record.tool_execution_id,
        status="succeeded",
        summary="Confirmed.",
        finished_at=current,
    )
    remaining = ApprovalRepository(session).list_for_conversation(tenant_id, conversation_id)
    _reopen_if_idle(session, tenant_id, conversation_id, actor, remaining)
    enqueue_event(
        session,
        tenant_id=tenant_id,
        correlation_id=actor.correlation_id,
        event_name=APPROVAL_CONSUMED,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        entities={"approval_id": record.id, "conversation_id": conversation_id},
        created_at=current,
    )
    return updated


def _owned(session: Session, tenant_id: UUID, customer_id: UUID, conversation_id: UUID) -> None:
    ConversationRepository(session).require_for_customer(tenant_id, customer_id, conversation_id)


def _wait(session: Session, tenant_id: UUID, conversation_id: UUID, actor: ActorContext) -> None:
    current = ConversationRepository(session).require(tenant_id, conversation_id)
    if current.status is ConversationStatus.WAITING_APPROVAL:
        return
    if current.status not in {ConversationStatus.OPEN, ConversationStatus.ESCALATED}:
        raise SupportError(
            "invalid_conversation_status",
            "This conversation cannot wait for confirmation.",
            409,
        )
    change_conversation_status(
        session,
        tenant_id,
        conversation_id,
        ConversationStatus.WAITING_APPROVAL,
        actor,
    )


def _reopen_if_idle(
    session: Session,
    tenant_id: UUID,
    conversation_id: UUID,
    actor: ActorContext,
    records: list[ApprovalRecord],
) -> None:
    if any(item.status is ApprovalStatus.PENDING for item in records):
        return
    current = ConversationRepository(session).require(tenant_id, conversation_id)
    if current.status is not ConversationStatus.WAITING_APPROVAL:
        return
    change_conversation_status(
        session,
        tenant_id,
        conversation_id,
        ConversationStatus.OPEN,
        actor,
    )


def _finish_execution(
    session: Session,
    tenant_id: UUID,
    execution_id: UUID,
    *,
    status: str,
    summary: str,
    finished_at: datetime,
) -> None:
    ToolExecutionRepository(session).finish(
        tenant_id,
        execution_id,
        status=status,
        summary=summary,
        finished_at=finished_at,
    )


def _system(actor: ActorContext) -> ActorContext:
    return ActorContext(
        actor_type="system",
        actor_id=actor.actor_id,
        correlation_id=actor.correlation_id,
    )


def _audit(
    session: Session,
    tenant_id: UUID,
    actor: ActorContext,
    *,
    action: str,
    approval_id: UUID,
    created_at: datetime,
    fields: dict[str, object],
) -> None:
    from assistflow_conversations.audit import audit_payload

    AuditRepository(session).append(
        AuditEventRecord(
            id=uuid4(),
            tenant_id=tenant_id,
            correlation_id=actor.correlation_id,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            action=action,
            target_type="approval",
            target_id=approval_id,
            payload=audit_payload(fields),
            created_at=created_at,
        )
    )
