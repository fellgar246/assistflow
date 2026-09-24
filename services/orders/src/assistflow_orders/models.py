"""Order table."""

from datetime import datetime
from uuid import UUID

from assistflow_customers.db import Base, UtcDateTime
from sqlalchemy import JSON, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column


class OrderRow(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "order_number", name="uq_orders_tenant_number"),
        Index("ix_orders_tenant_created", "tenant_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    customer_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("customers.id"))
    order_number: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    currency: Mapped[str] = mapped_column(String(3))
    total_cents: Mapped[int] = mapped_column(Integer)
    shipping_address: Mapped[dict[str, object]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
