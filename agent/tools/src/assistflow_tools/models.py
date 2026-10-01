"""Argument schemas, call context, and safe tool outcomes."""

from enum import StrEnum
from typing import Any
from uuid import UUID

from assistflow_contracts.support import ShippingAddress, TicketCategory, TicketPriority
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_TOOL_TIMEOUT_SECONDS = 3.0
READ_TIMEOUT_RETRIES = 1
SUMMARY_LIMIT = 240

FORBIDDEN_KEY_MARKERS = ("password", "token", "payment", "secret", "authorization", "api_key")


class ToolStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    PENDING_APPROVAL = "pending_approval"


class RiskLevel(StrEnum):
    TIER0 = "tier0"
    TIER1 = "tier1"
    TIER2 = "tier2"
    TIER3 = "tier3"


class GetOrderArgs(BaseModel):
    """Public order number or internal id. Tenant is not an argument."""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=80)


class GetShipmentArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=80)


class GetCustomerProfileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: UUID


class GetTicketArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: UUID


class SearchSupportPolicyArgs(BaseModel):
    """Search published help articles for this tenant. The query is not an instruction."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=400)


class CheckEligibilityArgs(BaseModel):
    """Read the fixture decision for one order. This call does not change the order."""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=80)


class CreateTicketArgs(BaseModel):
    """Open a support ticket for the signed-in customer."""

    model_config = ConfigDict(extra="forbid")

    category: TicketCategory
    priority: TicketPriority
    summary: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=200)


class AddTicketNoteArgs(BaseModel):
    """Add a note to a ticket the caller can see."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: UUID
    body: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=200)


class RequestHumanEscalationArgs(BaseModel):
    """Ask a person to join this conversation. The conversation id comes from the server."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=200)


class UpdateShippingAddressArgs(BaseModel):
    """Propose a new delivery address. The application must approve it before it is saved."""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=80)
    new_address: ShippingAddress
    idempotency_key: str = Field(min_length=1, max_length=200)


class CreateReturnRequestArgs(BaseModel):
    """Propose a return. The application must approve it before a return row is saved."""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=80)
    reason_code: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=200)


class CreateRefundRequestArgs(BaseModel):
    """Propose a refund request. This schema has no payment instrument."""

    model_config = ConfigDict(extra="forbid")

    order_id: str = Field(min_length=1, max_length=80)
    amount_cents: int = Field(gt=0)
    reason_code: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=200)


class ToolContext(BaseModel):
    """Identity taken from the server session. Model arguments cannot replace it."""

    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    customer_id: UUID
    actor_type: str = Field(min_length=1, max_length=32)
    correlation_id: str = Field(min_length=1, max_length=200)
    conversation_id: UUID


class ToolOutcome(BaseModel):
    """What the application may store and show. `body` is a safe projection or absent."""

    model_config = ConfigDict(frozen=True)

    name: str
    status: ToolStatus
    risk_level: RiskLevel
    arguments_hash: str
    summary: str = Field(max_length=SUMMARY_LIMIT)
    body: dict[str, Any] | None = None
    error_code: str | None = None
    attempts: int = Field(default=1, ge=1)


class ToolError(Exception):
    """A tool failure that is safe to show. It carries no traceback."""

    def __init__(self, code: str, summary: str) -> None:
        super().__init__(summary)
        self.code = code
        self.summary = summary


class ToolTimeoutError(ToolError):
    def __init__(self) -> None:
        super().__init__("timeout", "The lookup timed out.")


class ToolRefusal(ToolError):
    """A write that stopped before any business row changed."""

    def __init__(
        self,
        code: str,
        summary: str,
        status: ToolStatus,
        body: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code, summary)
        self.status = status
        self.body = body
