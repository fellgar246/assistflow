"""Shared schemas. This package performs no input or output."""

from assistflow_contracts.conversation import (
    Conversation,
    ConversationPage,
    ConversationStatus,
    CustomerMessageCreate,
    Message,
    MessagePage,
    MessageRole,
    OpenConversation,
)
from assistflow_contracts.health import HealthStatus
from assistflow_contracts.support import (
    Customer,
    CustomerPage,
    Eligibility,
    Order,
    OrderPage,
    Problem,
    RefundEligibility,
    ReturnEligibility,
    Shipment,
    Ticket,
    TicketCreate,
    TicketPage,
)

__all__ = [
    "Conversation",
    "ConversationPage",
    "ConversationStatus",
    "Customer",
    "CustomerMessageCreate",
    "CustomerPage",
    "Eligibility",
    "HealthStatus",
    "Message",
    "MessagePage",
    "MessageRole",
    "OpenConversation",
    "Order",
    "OrderPage",
    "Problem",
    "RefundEligibility",
    "ReturnEligibility",
    "Shipment",
    "Ticket",
    "TicketCreate",
    "TicketPage",
]
