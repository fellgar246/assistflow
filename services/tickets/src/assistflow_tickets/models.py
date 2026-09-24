"""Support ticket table."""

from datetime import datetime
from uuid import UUID

from assistflow_customers.db import Base, UtcDateTime
from sqlalchemy import ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column


class TicketRow(Base):
    __tablename__ = "tickets"
    __table_args__ = (Index("ix_tickets_tenant_created", "tenant_id", "created_at", "id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    customer_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("customers.id"))
    conversation_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("conversations.id"), nullable=True
    )
    priority: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(String(500))
    assigned_to: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
