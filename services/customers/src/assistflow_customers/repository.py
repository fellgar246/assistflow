"""Tenant-scoped customer reads and writes."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from assistflow_contracts.support import CustomerStatus
from sqlalchemy import select
from sqlalchemy.orm import Session

from assistflow_customers.errors import SupportError, require_tenant_id
from assistflow_customers.models import CommandIdempotencyRow, CustomerRow, ToolIdempotencyRow
from assistflow_customers.paging import RecordPage, apply_keyset, decode_cursor, split_page


@dataclass(frozen=True)
class CustomerRecord:
    id: UUID
    tenant_id: UUID
    email: str
    display_name: str
    status: CustomerStatus
    created_at: datetime


@dataclass(frozen=True)
class IdempotencyHit:
    arguments_hash: str
    result_json: dict[str, object]


@dataclass(frozen=True)
class ToolIdempotencyHit:
    tool_name: str
    arguments_hash: str
    result_summary: dict[str, object]


def _customer(row: CustomerRow) -> CustomerRecord:
    return CustomerRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        email=row.email,
        display_name=row.display_name,
        status=CustomerStatus(row.status),
        created_at=row.created_at,
    )


class CustomerRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, tenant_id: UUID, customer_id: UUID) -> CustomerRecord | None:
        tenant_id = require_tenant_id(tenant_id)
        row = self._session.scalar(
            select(CustomerRow).where(
                CustomerRow.tenant_id == tenant_id,
                CustomerRow.id == customer_id,
            )
        )
        return None if row is None else _customer(row)

    def get_by_email(self, tenant_id: UUID, email: str) -> CustomerRecord | None:
        tenant_id = require_tenant_id(tenant_id)
        row = self._session.scalar(
            select(CustomerRow).where(
                CustomerRow.tenant_id == tenant_id,
                CustomerRow.email == email,
            )
        )
        return None if row is None else _customer(row)

    def require(self, tenant_id: UUID, customer_id: UUID) -> CustomerRecord:
        found = self.get(tenant_id, customer_id)
        if found is None:
            raise SupportError(
                "customer_not_found",
                f"Customer {customer_id} was not found.",
                404,
            )
        return found

    def list(
        self, tenant_id: UUID, *, cursor: str | None, limit: int
    ) -> RecordPage[CustomerRecord]:
        tenant_id = require_tenant_id(tenant_id)
        statement = apply_keyset(
            select(CustomerRow).where(CustomerRow.tenant_id == tenant_id),
            CustomerRow.created_at,
            CustomerRow.id,
            decode_cursor(cursor) if cursor else None,
        )
        rows = [_customer(row) for row in self._session.scalars(statement.limit(limit + 1))]
        return split_page(rows, limit, lambda item: item.created_at, lambda item: item.id)

    def insert(self, record: CustomerRecord) -> None:
        require_tenant_id(record.tenant_id)
        self._session.add(
            CustomerRow(
                id=record.id,
                tenant_id=record.tenant_id,
                email=record.email,
                display_name=record.display_name,
                status=record.status.value,
                created_at=record.created_at,
            )
        )

    def update(self, record: CustomerRecord) -> None:
        require_tenant_id(record.tenant_id)
        row = self._session.get(CustomerRow, record.id)
        if row is None or row.tenant_id != record.tenant_id:
            raise SupportError(
                "customer_not_found",
                f"Customer {record.id} was not found.",
                404,
            )
        row.email = record.email
        row.display_name = record.display_name
        row.status = record.status.value


class IdempotencyRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find(
        self, tenant_id: UUID, command_name: str, idempotency_key: str
    ) -> IdempotencyHit | None:
        tenant_id = require_tenant_id(tenant_id)
        row = self._session.scalar(
            select(CommandIdempotencyRow).where(
                CommandIdempotencyRow.tenant_id == tenant_id,
                CommandIdempotencyRow.command_name == command_name,
                CommandIdempotencyRow.idempotency_key == idempotency_key,
            )
        )
        if row is None:
            return None
        result = row.result_json
        if not isinstance(result, dict):
            raise SupportError("internal_error", "Stored command result is invalid.", 500)
        return IdempotencyHit(arguments_hash=row.arguments_hash, result_json=dict(result))

    def save(
        self,
        *,
        record_id: UUID,
        tenant_id: UUID,
        command_name: str,
        idempotency_key: str,
        arguments_hash: str,
        result_json: dict[str, object],
        created_at: datetime,
    ) -> None:
        require_tenant_id(tenant_id)
        self._session.add(
            CommandIdempotencyRow(
                id=record_id,
                tenant_id=tenant_id,
                command_name=command_name,
                idempotency_key=idempotency_key,
                arguments_hash=arguments_hash,
                result_json=result_json,
                created_at=created_at,
            )
        )


def replay_or_conflict(hit: IdempotencyHit | None, arguments_hash: str) -> dict[str, object] | None:
    """Return the stored result, or None when this key has not been used."""
    if hit is None:
        return None
    if hit.arguments_hash != arguments_hash:
        raise SupportError(
            "idempotency_conflict",
            "This idempotency key was already used with different arguments.",
            409,
        )
    return hit.result_json


class ToolIdempotencyRepository:
    """Replay store for tool writes. Uniqueness is the tenant and the client key."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def find(self, tenant_id: UUID, idempotency_key: str) -> ToolIdempotencyHit | None:
        tenant_id = require_tenant_id(tenant_id)
        row = self._session.scalar(
            select(ToolIdempotencyRow).where(
                ToolIdempotencyRow.tenant_id == tenant_id,
                ToolIdempotencyRow.idempotency_key == idempotency_key,
            )
        )
        if row is None:
            return None
        result = row.result_summary
        if not isinstance(result, dict):
            raise SupportError("internal_error", "Stored tool result is invalid.", 500)
        return ToolIdempotencyHit(
            tool_name=row.tool_name,
            arguments_hash=row.arguments_hash,
            result_summary=dict(result),
        )

    def save(
        self,
        *,
        record_id: UUID,
        tenant_id: UUID,
        tool_name: str,
        idempotency_key: str,
        arguments_hash: str,
        result_summary: dict[str, object],
        created_at: datetime,
    ) -> None:
        require_tenant_id(tenant_id)
        self._session.add(
            ToolIdempotencyRow(
                id=record_id,
                tenant_id=tenant_id,
                tool_name=tool_name,
                idempotency_key=idempotency_key,
                arguments_hash=arguments_hash,
                result_summary=result_summary,
                created_at=created_at,
            )
        )
