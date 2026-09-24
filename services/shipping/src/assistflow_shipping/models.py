"""Shipment table."""

from datetime import date, datetime
from uuid import UUID

from assistflow_customers.db import Base, UtcDateTime
from sqlalchemy import Boolean, Date, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column


class ShipmentRow(Base):
    __tablename__ = "shipments"
    __table_args__ = (UniqueConstraint("tenant_id", "order_id", name="uq_shipments_tenant_order"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)
    order_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("orders.id"))
    carrier_name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(32))
    origin_hub: Mapped[str] = mapped_column(String(64))
    estimated_delivery_on: Mapped[date | None] = mapped_column(Date)
    address_change_eligible: Mapped[bool] = mapped_column(Boolean)
    shipped_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
