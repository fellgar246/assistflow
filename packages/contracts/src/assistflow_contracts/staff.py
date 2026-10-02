"""Staff inbox, trace summary, and ticket detail.

These payloads omit raw model prompts, tool arguments, and provider responses.
"""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from assistflow_contracts.conversation import ConversationChannel, ConversationStatus
from assistflow_contracts.support import (
    JsonDateTime,
    TicketCategory,
    TicketPriority,
    TicketStatus,
)


class InboxQueue(StrEnum):
    ALL = "all"
    ESCALATED = "escalated"
    WAITING_APPROVAL = "waiting_approval"


class StaffCommand(BaseModel):
    """Take over or resolve. The effect is stored once for this key."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=200)


class StaffMessageCreate(BaseModel):
    """A reply the customer can read. The server marks it as a person."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=8000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class StaffConversation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    customer_id: UUID
    customer_display_name: str
    channel: ConversationChannel
    status: ConversationStatus
    assigned_to: UUID | None
    assignee_name: str | None
    ticket_id: UUID | None
    ticket_priority: TicketPriority | None
    pending_approval_count: int = Field(ge=0)
    preview: str | None
    created_at: JsonDateTime
    updated_at: JsonDateTime


class InboxCounts(BaseModel):
    model_config = ConfigDict(frozen=True)

    all: int = Field(ge=0)
    escalated: int = Field(ge=0)
    waiting_approval: int = Field(ge=0)


class StaffInboxPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[StaffConversation]
    next_cursor: str | None
    counts: InboxCounts


class TraceStepView(BaseModel):
    """One step a person can read. It does not carry a provider payload."""

    model_config = ConfigDict(frozen=True)

    step: int = Field(ge=1)
    kind: str
    tool_name: str | None = None
    status: str | None = None
    latency_ms: int = Field(ge=0)
    error_code: str | None = None
    detail: str
    arguments_hash: str | None = None


class TraceTurnView(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    stop_reason: str
    created_at: JsonDateTime
    steps: list[TraceStepView]
    step_count: int = Field(ge=0)
    step_limit: int = Field(ge=1)
    tool_call_count: int = Field(ge=0)
    tool_call_limit: int = Field(ge=1)
    total_latency_ms: int = Field(ge=0)
    stopped_by_limit: bool


class TraceSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[TraceTurnView]


class TicketNoteView(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    body: str
    author_type: str
    created_at: JsonDateTime


class TicketDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    customer_display_name: str
    priority: TicketPriority
    category: TicketCategory
    status: TicketStatus
    summary: str
    conversation_id: UUID | None
    assigned_to: UUID | None
    assignee_name: str | None
    created_at: JsonDateTime
    notes: list[TicketNoteView]
