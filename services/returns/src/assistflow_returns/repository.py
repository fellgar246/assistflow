"""Tenant-scoped return request reads and writes."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from assistflow_contracts.support import ReturnStatus
from assistflow_customers.errors import SupportError, require_tenant_id
from sqlalchemy import select
from sqlalchemy.orm import Session

from assistflow_returns.models import ReturnRequestRow

_OPEN_STATUSES = {ReturnStatus.REQUESTED.value, ReturnStatus.APPROVED.value}


@dataclass(frozen=True)
class ReturnRecord:
    id: UUID
    tenant_id: UUID
    order_id: UUID
    status: ReturnStatus
    reason_code: str
    created_at: datetime


def _return(row: ReturnRequestRow) -> ReturnRecord:
    return ReturnRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        order_id=row.order_id,
        status=ReturnStatus(row.status),
        reason_code=row.reason_code,
        created_at=row.created_at,
    )


class ReturnRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, tenant_id: UUID, return_id: UUID) -> ReturnRecord | None:
        tenant_id = require_tenant_id(tenant_id)
        row = self._session.scalar(
            select(ReturnRequestRow).where(
                ReturnRequestRow.tenant_id == tenant_id,
                ReturnRequestRow.id == return_id,
            )
        )
        return None if row is None else _return(row)

    def has_open_return(self, tenant_id: UUID, order_id: UUID) -> bool:
        tenant_id = require_tenant_id(tenant_id)
        row = self._session.scalar(
            select(ReturnRequestRow.id).where(
                ReturnRequestRow.tenant_id == tenant_id,
                ReturnRequestRow.order_id == order_id,
                ReturnRequestRow.status.in_(_OPEN_STATUSES),
            )
        )
        return row is not None

    def insert(self, record: ReturnRecord) -> None:
        require_tenant_id(record.tenant_id)
        self._session.add(
            ReturnRequestRow(
                id=record.id,
                tenant_id=record.tenant_id,
                order_id=record.order_id,
                status=record.status.value,
                reason_code=record.reason_code,
                created_at=record.created_at,
            )
        )

    def require(self, tenant_id: UUID, return_id: UUID) -> ReturnRecord:
        found = self.get(tenant_id, return_id)
        if found is None:
            raise SupportError("return_not_found", "Return request was not found.", 404)
        return found
