"""Tenant-scoped conversation, message, and audit access."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from assistflow_contracts.conversation import ConversationChannel, ConversationStatus, MessageRole
from assistflow_customers.errors import SupportError, require_tenant_id
from assistflow_customers.paging import RecordPage, apply_keyset, decode_cursor, split_page
from sqlalchemy import select
from sqlalchemy.orm import Session

from assistflow_conversations.models import (
    AgentTraceRow,
    AgentTraceStepRow,
    AuditEventRow,
    ConversationRow,
    MessageRow,
    ToolExecutionRow,
)


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

    def has_role(self, tenant_id: UUID, conversation_id: UUID, role: MessageRole) -> bool:
        """True when this conversation already has a message with the given role."""
        ConversationRepository(self._session).require(tenant_id, conversation_id)
        found = self._session.scalar(
            select(MessageRow.id)
            .where(
                MessageRow.conversation_id == conversation_id,
                MessageRow.role == role.value,
            )
            .limit(1)
        )
        return found is not None

    def first_customer_contents(
        self, tenant_id: UUID, conversation_ids: list[UUID]
    ) -> dict[UUID, str]:
        """Earliest customer text for each conversation, used as the list title."""
        require_tenant_id(tenant_id)
        if not conversation_ids:
            return {}
        rows = self._session.scalars(
            select(MessageRow)
            .where(
                MessageRow.conversation_id.in_(conversation_ids),
                MessageRow.role == MessageRole.CUSTOMER.value,
            )
            .order_by(MessageRow.created_at, MessageRow.id)
        )
        found: dict[UUID, str] = {}
        for row in rows:
            if row.conversation_id not in found:
                found[row.conversation_id] = row.content
        return found

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


@dataclass(frozen=True)
class AgentTraceStepRecord:
    id: UUID
    step_index: int
    kind: str
    latency_ms: int
    input_summary: str


@dataclass(frozen=True)
class AgentTraceRecord:
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    customer_id: UUID
    correlation_id: str
    prompt_id: str
    prompt_version: str
    stop_reason: str
    input_tokens: int
    output_tokens: int
    provider: str
    model_id: str
    created_at: datetime
    steps: tuple[AgentTraceStepRecord, ...]


class AgentTraceRepository:
    """Traces are read and written with an explicit tenant scope."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def insert(self, record: AgentTraceRecord) -> None:
        require_tenant_id(record.tenant_id)
        ConversationRepository(self._session).require(record.tenant_id, record.conversation_id)
        self._session.add(
            AgentTraceRow(
                id=record.id,
                tenant_id=record.tenant_id,
                conversation_id=record.conversation_id,
                customer_id=record.customer_id,
                correlation_id=record.correlation_id,
                prompt_id=record.prompt_id,
                prompt_version=record.prompt_version,
                stop_reason=record.stop_reason,
                input_tokens=record.input_tokens,
                output_tokens=record.output_tokens,
                provider=record.provider,
                model_id=record.model_id,
                created_at=record.created_at,
            )
        )
        for step in record.steps:
            self._session.add(
                AgentTraceStepRow(
                    id=step.id,
                    trace_id=record.id,
                    step_index=step.step_index,
                    kind=step.kind,
                    latency_ms=step.latency_ms,
                    input_summary=step.input_summary,
                )
            )

    def get(self, tenant_id: UUID, trace_id: UUID) -> AgentTraceRecord | None:
        tenant_id = require_tenant_id(tenant_id)
        row = self._session.scalar(
            select(AgentTraceRow).where(
                AgentTraceRow.tenant_id == tenant_id,
                AgentTraceRow.id == trace_id,
            )
        )
        if row is None:
            return None
        return _trace(row, self._steps(row.id))

    def list_for_conversation(
        self, tenant_id: UUID, conversation_id: UUID
    ) -> list[AgentTraceRecord]:
        tenant_id = require_tenant_id(tenant_id)
        ConversationRepository(self._session).require(tenant_id, conversation_id)
        rows = self._session.scalars(
            select(AgentTraceRow)
            .where(
                AgentTraceRow.tenant_id == tenant_id,
                AgentTraceRow.conversation_id == conversation_id,
            )
            .order_by(AgentTraceRow.created_at, AgentTraceRow.id)
        )
        return [_trace(row, self._steps(row.id)) for row in rows]

    def _steps(self, trace_id: UUID) -> tuple[AgentTraceStepRecord, ...]:
        rows = self._session.scalars(
            select(AgentTraceStepRow)
            .where(AgentTraceStepRow.trace_id == trace_id)
            .order_by(AgentTraceStepRow.step_index)
        )
        return tuple(
            AgentTraceStepRecord(
                id=row.id,
                step_index=row.step_index,
                kind=row.kind,
                latency_ms=row.latency_ms,
                input_summary=row.input_summary,
            )
            for row in rows
        )


def _trace(row: AgentTraceRow, steps: tuple[AgentTraceStepRecord, ...]) -> AgentTraceRecord:
    return AgentTraceRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        conversation_id=row.conversation_id,
        customer_id=row.customer_id,
        correlation_id=row.correlation_id,
        prompt_id=row.prompt_id,
        prompt_version=row.prompt_version,
        stop_reason=row.stop_reason,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        provider=row.provider,
        model_id=row.model_id,
        created_at=row.created_at,
        steps=steps,
    )


@dataclass(frozen=True)
class ToolExecutionRecord:
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    correlation_id: str
    assistant_message_id: UUID | None
    tool_name: str
    arguments_hash: str
    status: str
    risk_level: str
    approval_id: UUID | None
    started_at: datetime
    finished_at: datetime | None
    result_summary: str


def _tool_execution(row: ToolExecutionRow) -> ToolExecutionRecord:
    return ToolExecutionRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        conversation_id=row.conversation_id,
        correlation_id=row.correlation_id,
        assistant_message_id=row.assistant_message_id,
        tool_name=row.tool_name,
        arguments_hash=row.arguments_hash,
        status=row.status,
        risk_level=row.risk_level,
        approval_id=row.approval_id,
        started_at=row.started_at,
        finished_at=row.finished_at,
        result_summary=row.result_summary,
    )


class ToolExecutionRepository:
    """Tool calls are stored and read with an explicit tenant scope."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def insert(self, record: ToolExecutionRecord) -> None:
        require_tenant_id(record.tenant_id)
        ConversationRepository(self._session).require(record.tenant_id, record.conversation_id)
        self._session.add(
            ToolExecutionRow(
                id=record.id,
                tenant_id=record.tenant_id,
                conversation_id=record.conversation_id,
                correlation_id=record.correlation_id,
                assistant_message_id=record.assistant_message_id,
                tool_name=record.tool_name,
                arguments_hash=record.arguments_hash,
                status=record.status,
                risk_level=record.risk_level,
                approval_id=record.approval_id,
                started_at=record.started_at,
                finished_at=record.finished_at,
                result_summary=record.result_summary,
            )
        )

    def attach_message(self, tenant_id: UUID, execution_ids: list[UUID], message_id: UUID) -> None:
        tenant_id = require_tenant_id(tenant_id)
        if not execution_ids:
            return
        rows = self._session.scalars(
            select(ToolExecutionRow).where(
                ToolExecutionRow.tenant_id == tenant_id,
                ToolExecutionRow.id.in_(execution_ids),
            )
        )
        for row in rows:
            row.assistant_message_id = message_id

    def list_for_conversation(
        self, tenant_id: UUID, conversation_id: UUID
    ) -> list[ToolExecutionRecord]:
        tenant_id = require_tenant_id(tenant_id)
        ConversationRepository(self._session).require(tenant_id, conversation_id)
        rows = self._session.scalars(
            select(ToolExecutionRow)
            .where(
                ToolExecutionRow.tenant_id == tenant_id,
                ToolExecutionRow.conversation_id == conversation_id,
            )
            .order_by(ToolExecutionRow.started_at, ToolExecutionRow.id)
        )
        return [_tool_execution(row) for row in rows]


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
