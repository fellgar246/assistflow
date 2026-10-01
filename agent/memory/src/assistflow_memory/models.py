"""Session events and preference rows. Both are tenant scoped."""

from datetime import datetime
from uuid import UUID

from assistflow_customers.db import Base, UtcDateTime
from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column


class SessionMemoryEventRow(Base):
    """One short-lived fact. The value is redacted before it is stored."""

    __tablename__ = "session_memory_events"
    __table_args__ = (
        Index(
            "ix_session_memory_events_session",
            "tenant_id",
            "conversation_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    customer_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("customers.id"))
    conversation_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("conversations.id"))
    kind: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)


class MemoryPreferenceRow(Base):
    """One allowed preference for one customer. Other keys are not stored."""

    __tablename__ = "memory_preferences"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "customer_id",
            "preference_key",
            name="uq_memory_preferences_owner_key",
        ),
        Index(
            "ix_memory_preferences_owner",
            "tenant_id",
            "customer_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    customer_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("customers.id"))
    preference_key: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(String(32))
    purpose: Mapped[str] = mapped_column(String(200))
    retention_deadline: Mapped[datetime] = mapped_column(UtcDateTime)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)
