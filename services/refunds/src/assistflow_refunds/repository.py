"""Tenant-scoped refund request reads and writes."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from assistflow_contracts.support import RefundStatus
from assistflow_customers.errors import require_tenant_id
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from assistflow_refunds.models import RefundRequestRow

_RESERVED = {
    RefundStatus.REQUESTED.value,
    RefundStatus.PENDING_REVIEW.value,
    RefundStatus.APPROVED.value,
}


@dataclass(frozen=True)
class RefundRecord:
    id: UUID
    tenant_id: UUID
    order_id: UUID
    return_request_id: UUID | None
    status: RefundStatus
    amount_cents: int
    currency: str
    created_at: datetime


class RefundRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def reserved_cents(self, tenant_id: UUID, order_id: UUID) -> int:
        tenant_id = require_tenant_id(tenant_id)
        total = self._session.scalar(
            select(func.coalesce(func.sum(RefundRequestRow.amount_cents), 0)).where(
                RefundRequestRow.tenant_id == tenant_id,
                RefundRequestRow.order_id == order_id,
                RefundRequestRow.status.in_(_RESERVED),
            )
        )
        return int(total or 0)

    def insert(self, record: RefundRecord) -> None:
        require_tenant_id(record.tenant_id)
        self._session.add(
            RefundRequestRow(
                id=record.id,
                tenant_id=record.tenant_id,
                order_id=record.order_id,
                return_request_id=record.return_request_id,
                status=record.status.value,
                amount_cents=record.amount_cents,
                currency=record.currency,
                created_at=record.created_at,
            )
        )
