"""Approval cards. The client never sends the arguments that will be written."""

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from assistflow_contracts.support import JsonDateTime, ShippingAddress


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CONSUMED = "consumed"


class AddressChange(BaseModel):
    """Current and proposed delivery address. Both are safe to show."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["address"] = "address"
    order_number: str = Field(min_length=1, max_length=80)
    current: ShippingAddress
    proposed: ShippingAddress


class ReturnChange(BaseModel):
    """A return proposal. It names a reason, not a payment instrument."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["return"] = "return"
    order_number: str = Field(min_length=1, max_length=80)
    reason_code: str = Field(min_length=1, max_length=64)
    reason_label: str = Field(min_length=1, max_length=80)


class RefundChange(BaseModel):
    """A refund request. The amount is in minor units. There is no card number."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["refund"] = "refund"
    order_number: str = Field(min_length=1, max_length=80)
    amount_cents: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    reason_code: str = Field(min_length=1, max_length=64)
    reason_label: str = Field(min_length=1, max_length=80)


ProposedChange = Annotated[
    AddressChange | ReturnChange | RefundChange,
    Field(discriminator="kind"),
]


class ApprovalView(BaseModel):
    """What the chat may render. Stored arguments stay on the server."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    action_type: str = Field(min_length=1, max_length=80)
    status: ApprovalStatus
    proposed_change: ProposedChange
    requested_at: JsonDateTime
    expires_at: JsonDateTime
    approved_at: JsonDateTime | None = None


class ApprovalDecision(BaseModel):
    """Confirm or cancel sends the approval id in the path and no new arguments."""

    model_config = ConfigDict(extra="forbid")
