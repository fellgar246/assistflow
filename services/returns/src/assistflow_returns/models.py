"""Return request table."""

from datetime import datetime
from uuid import UUID

from assistflow_customers.db import Base, UtcDateTime
from sqlalchemy import ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column


class ReturnRequestRow(Base):
    __tablename__ = "return_requests"
    __table_args__ = (Index("ix_return_requests_tenant_order", "tenant_id", "order_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    order_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("orders.id"))
    status: Mapped[str] = mapped_column(String(32))
    reason_code: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
