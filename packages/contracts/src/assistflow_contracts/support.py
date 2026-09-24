"""Customer, order, shipment, ticket, and eligibility payloads."""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer


def _json_datetime(value: datetime) -> str:
    utc = value.astimezone(UTC).replace(tzinfo=None)
    rendered = utc.isoformat(timespec="seconds") if utc.microsecond == 0 else utc.isoformat()
    return f"{rendered}Z"


JsonDateTime = Annotated[datetime, PlainSerializer(_json_datetime, when_used="json")]


class CustomerStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class OrderStatus(StrEnum):
    PLACED = "placed"
    PAID = "paid"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"


class ShipmentStatus(StrEnum):
    PENDING = "pending"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    EXCEPTION = "exception"


class ReturnStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    RECEIVED = "received"


class RefundStatus(StrEnum):
    REQUESTED = "requested"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class TicketPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class TicketCategory(StrEnum):
    ORDER = "order"
    SHIPPING = "shipping"
    RETURN = "return"
    REFUND = "refund"
    ACCOUNT = "account"
    OTHER = "other"


class TicketStatus(StrEnum):
    OPEN = "open"
    PENDING = "pending"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


RETURN_REASON_CODES: tuple[str, ...] = (
    "damaged",
    "wrong_item",
    "not_as_described",
    "changed_mind",
    "other",
)


class Problem(BaseModel):
    """Stable error body. Responses never include a stack trace."""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str


class ShippingAddress(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    recipient: str
    line1: str
    line2: str | None = None
    city: str
    region: str
    postal_code: str
    country: str


class ShipmentSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    carrier_name: str
    status: ShipmentStatus
    origin_hub: str
    estimated_delivery_on: date | None
    address_change_eligible: bool
    shipped_at: JsonDateTime | None


class Order(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_number: str
    status: OrderStatus
    currency: str
    total_cents: int
    shipping_address: ShippingAddress
    created_at: JsonDateTime
    shipment: ShipmentSummary | None


class OrderPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[Order]
    next_cursor: str | None


class Shipment(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_number: str
    carrier_name: str
    status: ShipmentStatus
    origin_hub: str
    estimated_delivery_on: date | None
    address_change_eligible: bool
    shipped_at: JsonDateTime | None


class Customer(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    email: str
    display_name: str
    status: CustomerStatus
    created_at: JsonDateTime


class CustomerPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[Customer]
    next_cursor: str | None


class Ticket(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    priority: TicketPriority
    category: TicketCategory
    status: TicketStatus
    summary: str
    conversation_id: UUID | None = None
    created_at: JsonDateTime


class TicketPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[Ticket]
    next_cursor: str | None


class TicketCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: UUID
    priority: TicketPriority
    category: TicketCategory
    summary: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=200)
    conversation_id: UUID | None = None


class Eligibility(BaseModel):
    model_config = ConfigDict(frozen=True)

    eligible: bool
    reason_code: str


class ReturnEligibility(BaseModel):
    model_config = ConfigDict(frozen=True)

    eligible: bool
    reason_code: str
    allowed_reason_codes: list[str]


class RefundEligibility(BaseModel):
    model_config = ConfigDict(frozen=True)

    eligible: bool
    reason_code: str
    maximum_amount_cents: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
