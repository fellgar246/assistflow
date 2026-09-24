"""Conversation, message, and transcript payloads."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from assistflow_contracts.support import JsonDateTime


class ConversationStatus(StrEnum):
    OPEN = "open"
    WAITING_APPROVAL = "waiting_approval"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


class MessageRole(StrEnum):
    CUSTOMER = "customer"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ConversationChannel(StrEnum):
    WEB = "web"


class Conversation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    customer_id: UUID
    channel: ConversationChannel
    status: ConversationStatus
    created_at: JsonDateTime
    updated_at: JsonDateTime


class ConversationPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[Conversation]
    next_cursor: str | None


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    role: MessageRole
    content: str
    created_at: JsonDateTime


class MessagePage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[Message]
    next_cursor: str | None


class OpenConversation(BaseModel):
    """Open a web conversation. Tenant and customer come from the dev actor, not this body."""

    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=200)


class CustomerMessageCreate(BaseModel):
    """Store a customer message. The server sets the role and does not call a model."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=8000)
    idempotency_key: str = Field(min_length=1, max_length=200)
