"""Tenant-scoped conversation, message, and audit access."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from assistflow_contracts.conversation import ConversationChannel, ConversationStatus, MessageRole
from assistflow_customers.errors import SupportError, require_tenant_id
from assistflow_customers.paging import RecordPage, apply_keyset, decode_cursor, split_page
from sqlalchemy import select
from sqlalchemy.orm import Session

from assistflow_conversations.models import AuditEventRow, ConversationRow, MessageRow


@dataclass(frozen=True)
class ConversationRecord:
    id: UUID
    tenant_id: UUID
    customer_id: UUID
    channel: ConversationChannel
    status: ConversationStatus
    agent_session_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class MessageRecord:
    id: UUID
    conversation_id: UUID
    role: MessageRole
    content: str
    created_at: datetime


@dataclass(frozen=True)
class AuditEventRecord:
    id: UUID
    tenant_id: UUID
    correlation_id: str
    actor_type: str
    actor_id: UUID
    action: str
    target_type: str
    target_id: UUID
    payload: dict[str, object]
    created_at: datetime


def _conversation(row: ConversationRow) -> ConversationRecord:
    return ConversationRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        customer_id=row.customer_id,
        channel=ConversationChannel(row.channel),
        status=ConversationStatus(row.status),
        agent_session_id=row.agent_session_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _message(row: MessageRow) -> MessageRecord:
    return MessageRecord(
        id=row.id,
        conversation_id=row.conversation_id,
        role=MessageRole(row.role),
        content=row.content,
        created_at=row.created_at,
    )


def _audit(row: AuditEventRow) -> AuditEventRecord:
    payload = row.payload if isinstance(row.payload, dict) else {}
    return AuditEventRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        correlation_id=row.correlation_id,
        actor_type=row.actor_type,
        actor_id=row.actor_id,
        action=row.action,
        target_type=row.target_type,
        target_id=row.target_id,
        payload=dict(payload),
        created_at=row.created_at,
    )


class ConversationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, tenant_id: UUID, conversation_id: UUID) -> ConversationRecord | None:
        tenant_id = require_tenant_id(tenant_id)
        row = self._session.scalar(
            select(ConversationRow).where(
                ConversationRow.tenant_id == tenant_id,
                ConversationRow.id == conversation_id,
            )
        )
        return None if row is None else _conversation(row)

    def require(self, tenant_id: UUID, conversation_id: UUID) -> ConversationRecord:
        found = self.get(tenant_id, conversation_id)
        if found is None:
            raise SupportError(
                "conversation_not_found",
                f"Conversation {conversation_id} was not found.",
                404,
            )
        return found

    def require_for_customer(
        self, tenant_id: UUID, customer_id: UUID, conversation_id: UUID
    ) -> ConversationRecord:
        found = self.require(tenant_id, conversation_id)
        if found.customer_id != customer_id:
            raise SupportError(
                "conversation_not_found",
                f"Conversation {conversation_id} was not found.",
                404,
            )
        return found

    def list_for_customer(
        self, tenant_id: UUID, customer_id: UUID, *, cursor: str | None, limit: int
    ) -> RecordPage[ConversationRecord]:
        tenant_id = require_tenant_id(tenant_id)
        statement = apply_keyset(
            select(ConversationRow).where(
                ConversationRow.tenant_id == tenant_id,
                ConversationRow.customer_id == customer_id,
            ),
            ConversationRow.created_at,
            ConversationRow.id,
            decode_cursor(cursor) if cursor else None,
        )
        rows = [_conversation(row) for row in self._session.scalars(statement.limit(limit + 1))]
        return split_page(rows, limit, lambda item: item.created_at, lambda item: item.id)

    def insert(self, record: ConversationRecord) -> None:
        require_tenant_id(record.tenant_id)
        self._session.add(
            ConversationRow(
                id=record.id,
                tenant_id=record.tenant_id,
                customer_id=record.customer_id,
                channel=record.channel.value,
                status=record.status.value,
                agent_session_id=record.agent_session_id,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
        )

    def update_status(self, record: ConversationRecord) -> None:
        require_tenant_id(record.tenant_id)
        row = self._session.get(ConversationRow, record.id)
        if row is None or row.tenant_id != record.tenant_id:
            raise SupportError(
                "conversation_not_found",
                f"Conversation {record.id} was not found.",
                404,
            )
        row.status = record.status.value
        row.updated_at = record.updated_at

    def touch(self, tenant_id: UUID, conversation_id: UUID, updated_at: datetime) -> None:
        require_tenant_id(tenant_id)
        row = self._session.get(ConversationRow, conversation_id)
        if row is None or row.tenant_id != tenant_id:
            raise SupportError(
                "conversation_not_found",
                f"Conversation {conversation_id} was not found.",
                404,
            )
        row.updated_at = updated_at


class MessageRepository:
    """Messages are read through the parent conversation so the tenant stays in scope."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_page(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        *,
        cursor: str | None,
        limit: int,
    ) -> RecordPage[MessageRecord]:
        ConversationRepository(self._session).require(tenant_id, conversation_id)
        statement = apply_keyset(
            select(MessageRow).where(MessageRow.conversation_id == conversation_id),
            MessageRow.created_at,
            MessageRow.id,
            decode_cursor(cursor) if cursor else None,
        )
        rows = [_message(row) for row in self._session.scalars(statement.limit(limit + 1))]
        return split_page(rows, limit, lambda item: item.created_at, lambda item: item.id)

    def list_all(self, tenant_id: UUID, conversation_id: UUID) -> list[MessageRecord]:
        """Load the transcript in creation order on the conversation index."""
        ConversationRepository(self._session).require(tenant_id, conversation_id)
        statement = (
            select(MessageRow)
            .where(MessageRow.conversation_id == conversation_id)
            .order_by(MessageRow.created_at, MessageRow.id)
        )
        return [_message(row) for row in self._session.scalars(statement)]

    def insert(self, tenant_id: UUID, record: MessageRecord) -> None:
        ConversationRepository(self._session).require(tenant_id, record.conversation_id)
        self._session.add(
            MessageRow(
                id=record.id,
                conversation_id=record.conversation_id,
                role=record.role.value,
                content=record.content,
                created_at=record.created_at,
            )
        )


class AuditRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, record: AuditEventRecord) -> None:
        require_tenant_id(record.tenant_id)
        self._session.add(
            AuditEventRow(
                id=record.id,
                tenant_id=record.tenant_id,
                correlation_id=record.correlation_id,
                actor_type=record.actor_type,
                actor_id=record.actor_id,
                action=record.action,
                target_type=record.target_type,
                target_id=record.target_id,
                payload=record.payload,
                created_at=record.created_at,
            )
        )

    def list_for_correlation(self, tenant_id: UUID, correlation_id: str) -> list[AuditEventRecord]:
        tenant_id = require_tenant_id(tenant_id)
        statement = (
            select(AuditEventRow)
            .where(
                AuditEventRow.tenant_id == tenant_id,
                AuditEventRow.correlation_id == correlation_id,
            )
            .order_by(AuditEventRow.created_at, AuditEventRow.id)
        )
        return [_audit(row) for row in self._session.scalars(statement)]
