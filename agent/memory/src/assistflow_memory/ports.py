"""Memory ports. Adapters perform the I/O."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from assistflow_contracts.memory import MemoryPreference, SessionFacts


class SessionMemory(Protocol):
    """Short-lived facts for one conversation. A remembered id is not permission."""

    def load(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        conversation_id: UUID,
        now: datetime,
    ) -> SessionFacts:
        """Return unexpired facts for this owner. Another tenant receives none."""

    def record(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        conversation_id: UUID,
        kind: str,
        value: str,
        now: datetime,
    ) -> None:
        """Store one redacted fact. The event cap refuses the write."""


class PreferenceMemory(Protocol):
    """Language and contact channel only. Each row has a purpose and a deadline."""

    def load(self, tenant_id: UUID, customer_id: UUID, now: datetime) -> list[MemoryPreference]:
        """Return unexpired preferences for this owner."""

    def remember(
        self,
        tenant_id: UUID,
        customer_id: UUID,
        key: str,
        value: str,
        now: datetime,
    ) -> MemoryPreference:
        """Store one allowed preference, or reject the write."""

    def delete(self, tenant_id: UUID, customer_id: UUID) -> None:
        """Remove every preference for this owner."""
