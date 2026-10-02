"""List evaluation intake markers. The golden scenarios do not require them."""

from dataclasses import dataclass
from uuid import UUID

from assistflow_conversations.models import EvaluationIntakeRow
from sqlalchemy import select
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class SamplingMarker:
    """One resolved conversation chosen by the sample rate."""

    id: UUID
    tenant_id: UUID
    conversation_id: UUID
    event_id: UUID


def list_sampling_markers(session: Session) -> list[SamplingMarker]:
    """Return intake rows, oldest first. An empty table is a valid result."""
    rows = session.scalars(
        select(EvaluationIntakeRow).order_by(
            EvaluationIntakeRow.created_at,
            EvaluationIntakeRow.id,
        )
    )
    return [
        SamplingMarker(
            id=row.id,
            tenant_id=row.tenant_id,
            conversation_id=row.conversation_id,
            event_id=row.event_id,
        )
        for row in rows
    ]
