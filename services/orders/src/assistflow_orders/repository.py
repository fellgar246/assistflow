"""Tenant-scoped order reads and writes."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from assistflow_contracts.support import OrderStatus, ShippingAddress
from assistflow_customers.errors import SupportError, require_tenant_id
from assistflow_customers.paging import RecordPage, apply_keyset, decode_cursor, split_page
from sqlalchemy import select
from sqlalchemy.orm import Session

from assistflow_orders.models import OrderRow


@dataclass(frozen=True)
class OrderRecord:
    id: UUID
    tenant_id: UUID
    customer_id: UUID
    order_number: str
    status: OrderStatus
    currency: str
    total_cents: int
    shipping_address: ShippingAddress
    created_at: datetime


def _order(row: OrderRow) -> OrderRecord:
    return OrderRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        customer_id=row.customer_id,
        order_number=row.order_number,
        status=OrderStatus(row.status),
        currency=row.currency,
        total_cents=row.total_cents,
        shipping_address=ShippingAddress.model_validate(row.shipping_address),
        created_at=row.created_at,
    )


class OrderRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, tenant_id: UUID, order_number: str) -> OrderRecord | None:
        tenant_id = require_tenant_id(tenant_id)
        row = self._session.scalar(
            select(OrderRow).where(
                OrderRow.tenant_id == tenant_id,
                OrderRow.order_number == order_number,
            )
        )
        return None if row is None else _order(row)

    def get_by_id(self, tenant_id: UUID, order_id: UUID) -> OrderRecord | None:
        tenant_id = require_tenant_id(tenant_id)
        row = self._session.scalar(
            select(OrderRow).where(OrderRow.tenant_id == tenant_id, OrderRow.id == order_id)
        )
        return None if row is None else _order(row)

    def require(self, tenant_id: UUID, order_number: str) -> OrderRecord:
        found = self.get(tenant_id, order_number)
        if found is None:
            raise SupportError("order_not_found", f"Order {order_number} was not found.", 404)
        return found

    def list_for_customer(
        self, tenant_id: UUID, customer_id: UUID, *, cursor: str | None, limit: int
    ) -> RecordPage[OrderRecord]:
        tenant_id = require_tenant_id(tenant_id)
        statement = apply_keyset(
            select(OrderRow).where(
                OrderRow.tenant_id == tenant_id,
                OrderRow.customer_id == customer_id,
            ),
            OrderRow.created_at,
            OrderRow.id,
            decode_cursor(cursor) if cursor else None,
        )
        rows = [_order(row) for row in self._session.scalars(statement.limit(limit + 1))]
        return split_page(rows, limit, lambda item: item.created_at, lambda item: item.id)

    def list(self, tenant_id: UUID, *, cursor: str | None, limit: int) -> RecordPage[OrderRecord]:
        tenant_id = require_tenant_id(tenant_id)
        statement = apply_keyset(
            select(OrderRow).where(OrderRow.tenant_id == tenant_id),
            OrderRow.created_at,
            OrderRow.id,
            decode_cursor(cursor) if cursor else None,
        )
        rows = [_order(row) for row in self._session.scalars(statement.limit(limit + 1))]
        return split_page(rows, limit, lambda item: item.created_at, lambda item: item.id)

    def insert(self, record: OrderRecord) -> None:
        require_tenant_id(record.tenant_id)
        self._session.add(
            OrderRow(
                id=record.id,
                tenant_id=record.tenant_id,
                customer_id=record.customer_id,
                order_number=record.order_number,
                status=record.status.value,
                currency=record.currency,
                total_cents=record.total_cents,
                shipping_address=record.shipping_address.model_dump(),
                created_at=record.created_at,
            )
        )

    def update(self, record: OrderRecord) -> None:
        require_tenant_id(record.tenant_id)
        row = self._session.get(OrderRow, record.id)
        if row is None or row.tenant_id != record.tenant_id:
            raise SupportError(
                "order_not_found", f"Order {record.order_number} was not found.", 404
            )
        row.customer_id = record.customer_id
        row.order_number = record.order_number
        row.status = record.status.value
        row.currency = record.currency
        row.total_cents = record.total_cents
        row.shipping_address = record.shipping_address.model_dump()
