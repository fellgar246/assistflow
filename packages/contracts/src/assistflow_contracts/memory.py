"""Session facts and stored preferences. This module performs no I/O."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

SESSION_MEMORY_CHANNEL = "session_memory"
PREFERENCE_MEMORY_CHANNEL = "preference_memory"


class SessionFacts(BaseModel):
    """Short-lived facts for one conversation. They are not a transcript."""

    model_config = ConfigDict(frozen=True)

    last_order_id: str | None = None
    last_shipment_status: str | None = None


class ScriptContext(BaseModel):
    """Bounded history plus session facts. The current message stays separate."""

    model_config = ConfigDict(frozen=True)

    history: list[str] = Field(default_factory=list)
    last_order_id: str | None = None
    last_shipment_status: str | None = None


class MemoryPreference(BaseModel):
    """One allowed preference. The owner is the tenant and the customer."""

    model_config = ConfigDict(frozen=True)

    key: str
    value: str
    purpose: str
    retention_deadline: datetime


class MemoryPreferenceList(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[MemoryPreference]
