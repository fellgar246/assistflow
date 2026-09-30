"""Argument schemas, call context, and safe tool outcomes."""

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_TOOL_TIMEOUT_SECONDS = 3.0
READ_TIMEOUT_RETRIES = 1
SUMMARY_LIMIT = 240

FORBIDDEN_KEY_MARKERS = ("password", "token", "payment", "secret", "authorization", "api_key")


class ToolStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


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
