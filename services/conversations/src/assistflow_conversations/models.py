"""Conversation, message, and audit tables."""

from datetime import datetime
from uuid import UUID

from assistflow_customers.db import Base, UtcDateTime
from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON


class ConversationRow(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index(
            "ix_conversations_tenant_customer_created",
            "tenant_id",
            "customer_id",
            "created_at",
            "id",
        ),
        Index(
            "ix_conversations_tenant_status_updated",
            "tenant_id",
            "status",
            "updated_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    customer_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("customers.id"))
    channel: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    agent_session_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    assigned_to: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)


class MessageRow(Base):
    """Message text is the user-visible turn or a safe tool summary. No chain of thought."""

    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversations.id"))
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    citations: Mapped[list[dict[str, str | None]]] = mapped_column(JSON, default=list)
    author_type: Mapped[str] = mapped_column(String(32), default="model")
    author_name: Mapped[str | None] = mapped_column(String(80), nullable=True)


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index(
            "ix_audit_events_tenant_correlation",
            "tenant_id",
            "correlation_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    correlation_id: Mapped[str] = mapped_column(String(200))
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[UUID] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[UUID] = mapped_column(Uuid)
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class AgentTraceRow(Base):
    """A turn trace. Steps stay in a child table and omit provider payloads."""

    __tablename__ = "agent_traces"
    __table_args__ = (
        Index(
            "ix_agent_traces_tenant_conversation",
            "tenant_id",
            "conversation_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    conversation_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversations.id"))
    customer_id: Mapped[UUID] = mapped_column(Uuid)
    correlation_id: Mapped[str] = mapped_column(String(200))
    prompt_id: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(40))
    stop_reason: Mapped[str] = mapped_column(String(32))
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(32), default="mock")
    model_id: Mapped[str] = mapped_column(String(200), default="mock")
    grounded_answer_failures: Mapped[int] = mapped_column(Integer, default=0)
    runtime_invocation_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class AgentTraceStepRow(Base):
    __tablename__ = "agent_trace_steps"
    __table_args__ = (Index("ix_agent_trace_steps_trace_index", "trace_id", "step_index"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    trace_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("agent_traces.id"))
    step_index: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    latency_ms: Mapped[int] = mapped_column(Integer)
    input_summary: Mapped[str] = mapped_column(String(240))


class ToolExecutionRow(Base):
    """One authorized tool call. The summary is a safe projection, not a raw payload."""

    __tablename__ = "tool_executions"
    __table_args__ = (
        Index(
            "ix_tool_executions_tenant_conversation",
            "tenant_id",
            "conversation_id",
            "started_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    conversation_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversations.id"))
    correlation_id: Mapped[str] = mapped_column(String(200))
    assistant_message_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("messages.id"), nullable=True
    )
    tool_name: Mapped[str] = mapped_column(String(80))
    arguments_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    risk_level: Mapped[str] = mapped_column(String(16))
    approval_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    result_summary: Mapped[str] = mapped_column(String(240))
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)


class ApprovalRequestRow(Base):
    """One customer decision for a sensitive change.

    The id is random. Arguments stay here so confirm cannot supply a new payload.
    """

    __tablename__ = "approval_requests"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_approval_requests_tenant_key",
        ),
        Index(
            "ix_approval_requests_tenant_conversation",
            "tenant_id",
            "conversation_id",
            "requested_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    conversation_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversations.id"))
    tool_execution_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("tool_executions.id"))
    assistant_message_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("messages.id"), nullable=True
    )
    action_type: Mapped[str] = mapped_column(String(80))
    proposed_change: Mapped[dict[str, object]] = mapped_column(JSON)
    arguments: Mapped[dict[str, object]] = mapped_column(JSON)
    arguments_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    requested_at: Mapped[datetime] = mapped_column(UtcDateTime)
    approved_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    approved_by: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
    idempotency_key: Mapped[str] = mapped_column(String(200))


class EventOutboxRow(Base):
    """A domain event written in the business transaction and published after commit."""

    __tablename__ = "event_outbox"
    __table_args__ = (Index("ix_event_outbox_status_created", "status", "created_at", "id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    correlation_id: Mapped[str] = mapped_column(String(200))
    event_name: Mapped[str] = mapped_column(String(64))
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[UUID] = mapped_column(Uuid)
    payload: Mapped[dict[str, str]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    published_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class SideEffectReceiptRow(Base):
    """One successful consumer delivery for an event id."""

    __tablename__ = "side_effect_receipts"
    __table_args__ = (
        UniqueConstraint(
            "consumer_name",
            "event_id",
            name="uq_side_effect_receipts_consumer_event",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    consumer_name: Mapped[str] = mapped_column(String(64))
    event_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class NotificationRow(Base):
    """In-app notice a console can list later. It does not store a raw model payload."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_notifications_event_id"),
        Index("ix_notifications_tenant_created", "tenant_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    event_id: Mapped[UUID] = mapped_column(Uuid)
    event_name: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(String(500))
    conversation_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    ticket_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class NotificationEmailRow(Base):
    """A logged email notice. No mailbox provider is called."""

    __tablename__ = "notification_emails"
    __table_args__ = (UniqueConstraint("event_id", name="uq_notification_emails_event_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    event_id: Mapped[UUID] = mapped_column(Uuid)
    body: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class ConversationSummaryRow(Base):
    """Short text stored after a conversation is resolved."""

    __tablename__ = "conversation_summaries"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_conversation_summaries_event_id"),
        Index(
            "ix_conversation_summaries_tenant_conversation",
            "tenant_id",
            "conversation_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    conversation_id: Mapped[UUID] = mapped_column(Uuid)
    event_id: Mapped[UUID] = mapped_column(Uuid)
    summary: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class EvaluationIntakeRow(Base):
    """A resolved conversation marked for later evaluation intake."""

    __tablename__ = "evaluation_intake"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_evaluation_intake_event_id"),
        Index("ix_evaluation_intake_tenant_created", "tenant_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    conversation_id: Mapped[UUID] = mapped_column(Uuid)
    event_id: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
