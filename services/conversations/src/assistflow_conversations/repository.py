"""Tenant-scoped conversation, message, and audit access."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from assistflow_contracts.approval import ApprovalStatus
from assistflow_contracts.conversation import ConversationChannel, ConversationStatus, MessageRole
from assistflow_customers.errors import SupportError, require_tenant_id
from assistflow_customers.paging import (
    RecordPage,
    apply_keyset,
    apply_keyset_desc,
    decode_cursor,
    split_page,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from assistflow_conversations.models import (
    AgentTraceRow,
    AgentTraceStepRow,
    ApprovalRequestRow,
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
    assigned_to: UUID | None = None


@dataclass(frozen=True)
class MessageRecord:
    id: UUID
    conversation_id: UUID
    role: MessageRole
    content: str
    created_at: datetime
    citations: tuple[tuple[str, str | None], ...] = ()
    author_type: str = "model"
    author_name: str | None = None


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
        assigned_to=row.assigned_to,
    )


def _citations(raw: object) -> tuple[tuple[str, str | None], ...]:
    if not isinstance(raw, list):
        return ()
    found: list[tuple[str, str | None]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        if not isinstance(title, str) or title == "":
            continue
        version = item.get("version")
        found.append((title, version if isinstance(version, str) else None))
    return tuple(found)


def _message(row: MessageRow) -> MessageRecord:
    return MessageRecord(
        id=row.id,
        conversation_id=row.conversation_id,
        role=MessageRole(row.role),
        content=row.content,
        created_at=row.created_at,
        citations=_citations(row.citations),
        author_type=row.author_type or "model",
        author_name=row.author_name,
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

    def list_by_status(
        self,
        tenant_id: UUID,
        statuses: tuple[ConversationStatus, ...],
        *,
        cursor: str | None,
        limit: int,
    ) -> RecordPage[ConversationRecord]:
        """Newest update first. An empty status list matches nothing."""
        tenant_id = require_tenant_id(tenant_id)
        if not statuses:
            return RecordPage(items=[], next_cursor=None)
        statement = apply_keyset_desc(
            select(ConversationRow).where(
                ConversationRow.tenant_id == tenant_id,
                ConversationRow.status.in_([item.value for item in statuses]),
            ),
            ConversationRow.updated_at,
            ConversationRow.id,
            decode_cursor(cursor) if cursor else None,
        )
        rows = [_conversation(row) for row in self._session.scalars(statement.limit(limit + 1))]
        return split_page(rows, limit, lambda item: item.updated_at, lambda item: item.id)

    def count_status(self, tenant_id: UUID, status: ConversationStatus) -> int:
        tenant_id = require_tenant_id(tenant_id)
        found = self._session.scalar(
            select(func.count())
            .select_from(ConversationRow)
            .where(
                ConversationRow.tenant_id == tenant_id,
                ConversationRow.status == status.value,
            )
        )
        return int(found or 0)

    def assign(
        self,
        tenant_id: UUID,
        conversation_id: UUID,
        assigned_to: UUID,
        updated_at: datetime,
    ) -> ConversationRecord:
        require_tenant_id(tenant_id)
        row = self._session.get(ConversationRow, conversation_id)
        if row is None or row.tenant_id != tenant_id:
            raise SupportError(
                "conversation_not_found",
                f"Conversation {conversation_id} was not found.",
                404,
            )
        row.assigned_to = assigned_to
        row.updated_at = updated_at
        self._session.flush()
        return _conversation(row)

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
                assigned_to=record.assigned_to,
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

    def latest_visible_contents(
        self, tenant_id: UUID, conversation_ids: list[UUID]
    ) -> dict[UUID, str]:
        """Last customer, assistant, or system line. Tool rows stay out of the preview."""
        if not conversation_ids:
            return {}
        ConversationRepository(self._session).require(tenant_id, conversation_ids[0])
        rows = self._session.scalars(
            select(MessageRow)
            .where(
                MessageRow.conversation_id.in_(conversation_ids),
                MessageRow.role != MessageRole.TOOL.value,
            )
            .order_by(MessageRow.created_at.desc(), MessageRow.id.desc())
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
                citations=[
                    {"title": title, "version": version} for title, version in record.citations
                ],
                author_type=record.author_type,
                author_name=record.author_name,
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
    grounded_answer_failures: int = 0
    runtime_invocation_id: str | None = None
    duration_ms: int | None = None


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
                grounded_answer_failures=record.grounded_answer_failures,
                runtime_invocation_id=record.runtime_invocation_id,
                duration_ms=record.duration_ms,
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
        grounded_answer_failures=row.grounded_answer_failures,
        runtime_invocation_id=row.runtime_invocation_id,
        duration_ms=row.duration_ms,
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
    error_code: str | None = None
    latency_ms: int = 0


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
        error_code=row.error_code,
        latency_ms=row.latency_ms,
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
                error_code=record.error_code,
                latency_ms=record.latency_ms,
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

    def get(self, tenant_id: UUID, execution_id: UUID) -> ToolExecutionRecord | None:
        tenant_id = require_tenant_id(tenant_id)
        row = self._session.get(ToolExecutionRow, execution_id)
        if row is None or row.tenant_id != tenant_id:
            return None
        return _tool_execution(row)

    def finish(
        self,
        tenant_id: UUID,
        execution_id: UUID,
        *,
        status: str,
        summary: str,
        finished_at: datetime,
    ) -> None:
        tenant_id = require_tenant_id(tenant_id)
        row = self._session.get(ToolExecutionRow, execution_id)
        if row is None or row.tenant_id != tenant_id:
            raise SupportError("tool_execution_not_found", "That tool call was not found.", 404)
        row.status = status
        row.result_summary = summary[:240]
        row.finished_at = finished_at


@dataclass(frozen=True)
class ApprovalRecord:
    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    tool_execution_id: UUID
    assistant_message_id: UUID | None
    action_type: str
    proposed_change: dict[str, object]
    arguments: dict[str, object]
    arguments_hash: str
    status: ApprovalStatus
    requested_at: datetime
    approved_at: datetime | None
    approved_by: UUID | None
    expires_at: datetime
    idempotency_key: str


def _approval(row: ApprovalRequestRow) -> ApprovalRecord:
    change = row.proposed_change if isinstance(row.proposed_change, dict) else {}
    arguments = row.arguments if isinstance(row.arguments, dict) else {}
    return ApprovalRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        conversation_id=row.conversation_id,
        tool_execution_id=row.tool_execution_id,
        assistant_message_id=row.assistant_message_id,
        action_type=row.action_type,
        proposed_change=dict(change),
        arguments=dict(arguments),
        arguments_hash=row.arguments_hash,
        status=ApprovalStatus(row.status),
        requested_at=row.requested_at,
        approved_at=row.approved_at,
        approved_by=row.approved_by,
        expires_at=row.expires_at,
        idempotency_key=row.idempotency_key,
    )


class ApprovalRepository:
    """Approvals are stored and read with an explicit tenant scope."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def insert(self, record: ApprovalRecord) -> None:
        require_tenant_id(record.tenant_id)
        ConversationRepository(self._session).require(record.tenant_id, record.conversation_id)
        self._session.add(
            ApprovalRequestRow(
                id=record.id,
                tenant_id=record.tenant_id,
                conversation_id=record.conversation_id,
                tool_execution_id=record.tool_execution_id,
                assistant_message_id=record.assistant_message_id,
                action_type=record.action_type,
                proposed_change=record.proposed_change,
                arguments=record.arguments,
                arguments_hash=record.arguments_hash,
                status=record.status.value,
                requested_at=record.requested_at,
                approved_at=record.approved_at,
                approved_by=record.approved_by,
                expires_at=record.expires_at,
                idempotency_key=record.idempotency_key,
            )
        )

    def find_by_key(self, tenant_id: UUID, idempotency_key: str) -> ApprovalRecord | None:
        tenant_id = require_tenant_id(tenant_id)
        row = self._session.scalar(
            select(ApprovalRequestRow).where(
                ApprovalRequestRow.tenant_id == tenant_id,
                ApprovalRequestRow.idempotency_key == idempotency_key,
            )
        )
        return None if row is None else _approval(row)

    def get_for_conversation(
        self, tenant_id: UUID, conversation_id: UUID, approval_id: UUID
    ) -> ApprovalRecord | None:
        tenant_id = require_tenant_id(tenant_id)
        row = self._session.scalar(
            select(ApprovalRequestRow).where(
                ApprovalRequestRow.tenant_id == tenant_id,
                ApprovalRequestRow.conversation_id == conversation_id,
                ApprovalRequestRow.id == approval_id,
            )
        )
        return None if row is None else _approval(row)

    def require_for_conversation(
        self, tenant_id: UUID, conversation_id: UUID, approval_id: UUID
    ) -> ApprovalRecord:
        found = self.get_for_conversation(tenant_id, conversation_id, approval_id)
        if found is None:
            raise SupportError("approval_not_found", "That confirmation was not found.", 404)
        return found

    def list_for_conversation(self, tenant_id: UUID, conversation_id: UUID) -> list[ApprovalRecord]:
        tenant_id = require_tenant_id(tenant_id)
        ConversationRepository(self._session).require(tenant_id, conversation_id)
        rows = self._session.scalars(
            select(ApprovalRequestRow)
            .where(
                ApprovalRequestRow.tenant_id == tenant_id,
                ApprovalRequestRow.conversation_id == conversation_id,
            )
            .order_by(ApprovalRequestRow.requested_at, ApprovalRequestRow.id)
        )
        return [_approval(row) for row in rows]

    def attach_message(self, tenant_id: UUID, approval_ids: list[UUID], message_id: UUID) -> None:
        tenant_id = require_tenant_id(tenant_id)
        if not approval_ids:
            return
        rows = self._session.scalars(
            select(ApprovalRequestRow).where(
                ApprovalRequestRow.tenant_id == tenant_id,
                ApprovalRequestRow.id.in_(approval_ids),
            )
        )
        for row in rows:
            if row.assistant_message_id is None:
                row.assistant_message_id = message_id

    def save_status(
        self,
        record: ApprovalRecord,
        *,
        status: ApprovalStatus,
        approved_at: datetime | None = None,
        approved_by: UUID | None = None,
    ) -> ApprovalRecord:
        require_tenant_id(record.tenant_id)
        row = self._session.get(ApprovalRequestRow, record.id)
        if row is None or row.tenant_id != record.tenant_id:
            raise SupportError("approval_not_found", "That confirmation was not found.", 404)
        row.status = status.value
        if approved_at is not None:
            row.approved_at = approved_at
        if approved_by is not None:
            row.approved_by = approved_by
        self._session.flush()
        return _approval(row)


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
