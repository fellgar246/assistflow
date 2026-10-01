"""Preference table. Only the two allowed keys are written."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from assistflow_contracts.memory import MemoryPreference
from assistflow_customers.errors import require_tenant_id
from assistflow_customers.repository import CustomerRepository
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from assistflow_memory.allowlist import PURPOSES, RETENTION_DAYS, validate_preference
from assistflow_memory.models import MemoryPreferenceRow
from assistflow_runtime.redaction import redact_text


class LocalPreferenceMemory:
    """Store language and contact channel for one customer until the deadline."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def load(self, tenant_id: UUID, customer_id: UUID, now: datetime) -> list[MemoryPreference]:
        tenant_id = require_tenant_id(tenant_id)
        CustomerRepository(self._session).require(tenant_id, customer_id)
        rows = self._session.scalars(
            select(MemoryPreferenceRow)
            .where(
                MemoryPreferenceRow.tenant_id == tenant_id,
                MemoryPreferenceRow.customer_id == customer_id,
                MemoryPreferenceRow.retention_deadline > now,
            )
            .order_by(MemoryPreferenceRow.preference_key)
        ).all()
        return [_preference(row) for row in rows]

    def remember(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        key: str,
        value: str,
        now: datetime,
    ) -> MemoryPreference:
        tenant_id = require_tenant_id(tenant_id)
        CustomerRepository(self._session).require(tenant_id, customer_id)
        if now.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        stored = validate_preference(key, value)
        purpose = redact_text(PURPOSES[key])
        deadline = now + timedelta(days=RETENTION_DAYS)
        row = self._session.scalar(
            select(MemoryPreferenceRow).where(
                MemoryPreferenceRow.tenant_id == tenant_id,
                MemoryPreferenceRow.customer_id == customer_id,
                MemoryPreferenceRow.preference_key == key,
            )
        )
        if row is None:
            row = MemoryPreferenceRow(
                id=uuid4(),
                tenant_id=tenant_id,
                customer_id=customer_id,
                preference_key=key,
                value=stored,
                purpose=purpose,
                retention_deadline=deadline,
                created_at=now,
                updated_at=now,
            )
            self._session.add(row)
        else:
            row.value = stored
            row.purpose = purpose
            row.retention_deadline = deadline
            row.updated_at = now
        self._session.flush()
        return _preference(row)

    def delete(self, tenant_id: UUID, customer_id: UUID) -> None:
        tenant_id = require_tenant_id(tenant_id)
        CustomerRepository(self._session).require(tenant_id, customer_id)
        self._session.execute(
            delete(MemoryPreferenceRow).where(
                MemoryPreferenceRow.tenant_id == tenant_id,
                MemoryPreferenceRow.customer_id == customer_id,
            )
        )
        self._session.flush()


def _preference(row: MemoryPreferenceRow) -> MemoryPreference:
    return MemoryPreference(
        key=row.preference_key,
        value=row.value,
        purpose=row.purpose,
        retention_deadline=row.retention_deadline,
    )
