"""Refund request table. A row is a request, not a captured payment."""

from datetime import datetime
from uuid import UUID

from assistflow_customers.db import Base, UtcDateTime
from sqlalchemy import ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column


class RefundRequestRow(Base):
    __tablename__ = "refund_requests"
    __table_args__ = (Index("ix_refund_requests_tenant_order", "tenant_id", "order_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    order_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("orders.id"))
    return_request_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("return_requests.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(32))
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
