"""Tenant-scoped ticket reads and writes."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from assistflow_contracts.support import TicketCategory, TicketPriority, TicketStatus
from assistflow_customers.errors import SupportError, require_tenant_id
from assistflow_customers.paging import RecordPage, apply_keyset, decode_cursor, split_page
from sqlalchemy import select
from sqlalchemy.orm import Session

from assistflow_tickets.models import TicketNoteRow, TicketRow


@dataclass(frozen=True)
class TicketRecord:
    id: UUID
    tenant_id: UUID
    customer_id: UUID
    conversation_id: UUID | None
    priority: TicketPriority
    category: TicketCategory
    status: TicketStatus
    summary: str
    assigned_to: UUID | None
    created_at: datetime


def _ticket(row: TicketRow) -> TicketRecord:
    return TicketRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        customer_id=row.customer_id,
        conversation_id=row.conversation_id,
        priority=TicketPriority(row.priority),
        category=TicketCategory(row.category),
        status=TicketStatus(row.status),
        summary=row.summary,
        assigned_to=row.assigned_to,
        created_at=row.created_at,
    )


class TicketRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, tenant_id: UUID, ticket_id: UUID) -> TicketRecord | None:
        tenant_id = require_tenant_id(tenant_id)
        row = self._session.scalar(
            select(TicketRow).where(TicketRow.tenant_id == tenant_id, TicketRow.id == ticket_id)
        )
        return None if row is None else _ticket(row)

    def require(self, tenant_id: UUID, ticket_id: UUID) -> TicketRecord:
        found = self.get(tenant_id, ticket_id)
        if found is None:
            raise SupportError("ticket_not_found", f"Ticket {ticket_id} was not found.", 404)
        return found

    def list_ids_for_conversation(self, tenant_id: UUID, conversation_id: UUID) -> list[UUID]:
        tenant_id = require_tenant_id(tenant_id)
        statement = (
            select(TicketRow.id)
            .where(
                TicketRow.tenant_id == tenant_id,
                TicketRow.conversation_id == conversation_id,
            )
            .order_by(TicketRow.created_at, TicketRow.id)
        )
        return list(self._session.scalars(statement))

    def list_for_customer(
        self, tenant_id: UUID, customer_id: UUID, *, cursor: str | None, limit: int
    ) -> RecordPage[TicketRecord]:
        tenant_id = require_tenant_id(tenant_id)
        statement = apply_keyset(
            select(TicketRow).where(
                TicketRow.tenant_id == tenant_id,
                TicketRow.customer_id == customer_id,
            ),
            TicketRow.created_at,
            TicketRow.id,
            decode_cursor(cursor) if cursor else None,
        )
        rows = [_ticket(row) for row in self._session.scalars(statement.limit(limit + 1))]
        return split_page(rows, limit, lambda item: item.created_at, lambda item: item.id)

    def list(self, tenant_id: UUID, *, cursor: str | None, limit: int) -> RecordPage[TicketRecord]:
        tenant_id = require_tenant_id(tenant_id)
        statement = apply_keyset(
            select(TicketRow).where(TicketRow.tenant_id == tenant_id),
            TicketRow.created_at,
            TicketRow.id,
            decode_cursor(cursor) if cursor else None,
        )
        rows = [_ticket(row) for row in self._session.scalars(statement.limit(limit + 1))]
        return split_page(rows, limit, lambda item: item.created_at, lambda item: item.id)

    def insert(self, record: TicketRecord) -> None:
        require_tenant_id(record.tenant_id)
        self._session.add(
            TicketRow(
                id=record.id,
                tenant_id=record.tenant_id,
                customer_id=record.customer_id,
                conversation_id=record.conversation_id,
                priority=record.priority.value,
                category=record.category.value,
                status=record.status.value,
                summary=record.summary,
                assigned_to=record.assigned_to,
                created_at=record.created_at,
            )
        )

    def update(self, record: TicketRecord) -> None:
        require_tenant_id(record.tenant_id)
        row = self._session.get(TicketRow, record.id)
        if row is None or row.tenant_id != record.tenant_id:
            raise SupportError("ticket_not_found", f"Ticket {record.id} was not found.", 404)
        row.customer_id = record.customer_id
        row.conversation_id = record.conversation_id
        row.priority = record.priority.value
        row.category = record.category.value
        row.status = record.status.value
        row.summary = record.summary
        row.assigned_to = record.assigned_to


@dataclass(frozen=True)
class TicketNoteRecord:
    id: UUID
    tenant_id: UUID
    ticket_id: UUID
    body: str
    created_at: datetime


class TicketNoteRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def insert(self, record: TicketNoteRecord) -> None:
        require_tenant_id(record.tenant_id)
        self._session.add(
            TicketNoteRow(
                id=record.id,
                tenant_id=record.tenant_id,
                ticket_id=record.ticket_id,
                body=record.body,
                created_at=record.created_at,
            )
        )
