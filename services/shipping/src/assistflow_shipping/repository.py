"""Tenant-scoped shipment reads and writes."""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from assistflow_contracts.support import ShipmentStatus
from assistflow_customers.errors import SupportError, require_tenant_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from assistflow_shipping.models import ShipmentRow


@dataclass(frozen=True)
class ShipmentRecord:
    id: UUID
    tenant_id: UUID
    order_id: UUID
    carrier_name: str
    status: ShipmentStatus
    origin_hub: str
    estimated_delivery_on: date | None
    address_change_eligible: bool
    shipped_at: datetime | None


def _shipment(row: ShipmentRow) -> ShipmentRecord:
    return ShipmentRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        order_id=row.order_id,
        carrier_name=row.carrier_name,
        status=ShipmentStatus(row.status),
        origin_hub=row.origin_hub,
        estimated_delivery_on=row.estimated_delivery_on,
        address_change_eligible=row.address_change_eligible,
        shipped_at=row.shipped_at,
    )


class ShipmentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_order(self, tenant_id: UUID, order_id: UUID) -> ShipmentRecord | None:
        tenant_id = require_tenant_id(tenant_id)
        row = self._session.scalar(
            select(ShipmentRow).where(
                ShipmentRow.tenant_id == tenant_id,
                ShipmentRow.order_id == order_id,
            )
        )
        return None if row is None else _shipment(row)

    def insert(self, record: ShipmentRecord) -> None:
        require_tenant_id(record.tenant_id)
        self._session.add(_row(record))

    def update(self, record: ShipmentRecord) -> None:
        require_tenant_id(record.tenant_id)
        row = self._session.get(ShipmentRow, record.id)
        if row is None or row.tenant_id != record.tenant_id:
            raise SupportError("shipment_not_found", "Shipment was not found.", 404)
        row.order_id = record.order_id
        row.carrier_name = record.carrier_name
        row.status = record.status.value
        row.origin_hub = record.origin_hub
        row.estimated_delivery_on = record.estimated_delivery_on
        row.address_change_eligible = record.address_change_eligible
        row.shipped_at = record.shipped_at


def _row(record: ShipmentRecord) -> ShipmentRow:
    return ShipmentRow(
        id=record.id,
        tenant_id=record.tenant_id,
        order_id=record.order_id,
        carrier_name=record.carrier_name,
        status=record.status.value,
        origin_hub=record.origin_hub,
        estimated_delivery_on=record.estimated_delivery_on,
        address_change_eligible=record.address_change_eligible,
        shipped_at=record.shipped_at,
    )
