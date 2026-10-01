"""Database session memory. Events expire within the session limit."""

import re
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from assistflow_contracts.memory import SessionFacts
from assistflow_customers.errors import require_tenant_id
from assistflow_customers.repository import CustomerRepository
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from assistflow_memory.limits import MemoryLimitError
from assistflow_memory.models import SessionMemoryEventRow
from assistflow_runtime.redaction import redact_text

ORDER_KIND = "last_order_id"
SHIPMENT_KIND = "last_shipment_status"
_KINDS = {ORDER_KIND, SHIPMENT_KIND}
_ORDER = re.compile(r"^ORD-\d+$")
_SHIPMENT_STATUSES = frozenset(
    {"pending", "in_transit", "out_for_delivery", "delivered", "exception"}
)


class LocalSessionMemory:
    """Store the last order id and shipment status until the session expires."""

    def __init__(self, session: Session, max_events: int, max_session_minutes: int) -> None:
        if max_events < 1:
            raise ValueError("MAX_MEMORY_EVENTS_PER_SESSION must be at least 1.")
        if max_session_minutes < 1:
            raise ValueError("MAX_SESSION_MINUTES must be at least 1.")
        self._session = session
        self._max_events = max_events
        self._ttl = timedelta(minutes=max_session_minutes)

    def load(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        conversation_id: UUID,
        now: datetime,
    ) -> SessionFacts:
        tenant_id = require_tenant_id(tenant_id)
        CustomerRepository(self._session).require(tenant_id, customer_id)
        rows = self._session.scalars(
            select(SessionMemoryEventRow)
            .where(
                SessionMemoryEventRow.tenant_id == tenant_id,
                SessionMemoryEventRow.customer_id == customer_id,
                SessionMemoryEventRow.conversation_id == conversation_id,
                SessionMemoryEventRow.expires_at > now,
            )
            .order_by(SessionMemoryEventRow.created_at, SessionMemoryEventRow.id)
        ).all()
        order_id: str | None = None
        status: str | None = None
        for row in rows:
            if row.kind == ORDER_KIND:
                order_id = row.value
            elif row.kind == SHIPMENT_KIND:
                status = row.value
        return SessionFacts(last_order_id=order_id, last_shipment_status=status)

    def record(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        conversation_id: UUID,
        kind: str,
        value: str,
        now: datetime,
    ) -> None:
        tenant_id = require_tenant_id(tenant_id)
        CustomerRepository(self._session).require(tenant_id, customer_id)
        if kind not in _KINDS:
            raise ValueError("Session memory accepts only an order id or a shipment status.")
        cleaned = clean_session_value(kind, redact_text(value).strip())
        if cleaned is None:
            return
        _aware(now)
        active = self._active_count(tenant_id, customer_id, conversation_id, now)
        if active >= self._max_events:
            raise MemoryLimitError(f"Session memory is limited to {self._max_events} events.")
        self._session.add(
            SessionMemoryEventRow(
                id=uuid4(),
                tenant_id=tenant_id,
                customer_id=customer_id,
                conversation_id=conversation_id,
                kind=kind,
                value=cleaned,
                created_at=now,
                expires_at=now + self._ttl,
            )
        )
        self._session.flush()

    def _active_count(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        conversation_id: UUID,
        now: datetime,
    ) -> int:
        counted = self._session.scalar(
            select(func.count())
            .select_from(SessionMemoryEventRow)
            .where(
                SessionMemoryEventRow.tenant_id == tenant_id,
                SessionMemoryEventRow.customer_id == customer_id,
                SessionMemoryEventRow.conversation_id == conversation_id,
                SessionMemoryEventRow.expires_at > now,
            )
        )
        return int(counted or 0)


def clean_session_value(kind: str, value: str) -> str | None:
    """Keep an order id or a known shipment status. Anything else is dropped."""
    if kind == ORDER_KIND and _ORDER.fullmatch(value):
        return value
    if kind == SHIPMENT_KIND and value in _SHIPMENT_STATUSES:
        return value
    return None


def _aware(value: datetime) -> None:
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
