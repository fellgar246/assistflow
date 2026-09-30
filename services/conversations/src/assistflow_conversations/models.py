"""Conversation, message, and audit tables."""

from datetime import datetime
from uuid import UUID

from assistflow_customers.db import Base, UtcDateTime
from sqlalchemy import ForeignKey, Index, Integer, String, Text, Uuid
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
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    customer_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("customers.id"))
    channel: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    agent_session_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
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
