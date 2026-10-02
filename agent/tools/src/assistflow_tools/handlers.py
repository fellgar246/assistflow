"""Thin adapters over support services. These functions do not issue SQL."""

import time
from collections.abc import Callable
from datetime import date
from uuid import UUID

from assistflow_contracts.observe import record_hop
from assistflow_customers.repository import CustomerRepository
from assistflow_orders.repository import OrderRecord, OrderRepository
from assistflow_shipping.repository import ShipmentRepository
from assistflow_tickets.repository import TicketRepository
from sqlalchemy.orm import Session

from assistflow_knowledge.embeddings import DeterministicEmbedding
from assistflow_knowledge.retriever import (
    DEFAULT_CHUNK_CAP,
    KnowledgeRetriever,
    LocalKnowledgeRetriever,
)
from assistflow_tools.faults import take_fault
from assistflow_tools.models import (
    GetCustomerProfileArgs,
    GetOrderArgs,
    GetShipmentArgs,
    GetTicketArgs,
    SearchSupportPolicyArgs,
    ToolContext,
    ToolError,
)
from assistflow_tools.projections import (
    project_customer,
    project_order,
    project_shipment,
    project_ticket,
)

Handler = Callable[[ToolContext, object], dict[str, object]]


def service_handlers(
    session: Session,
    *,
    today: date | None = None,
    retriever: KnowledgeRetriever | None = None,
) -> dict[str, Handler]:
    """Bind the read tools, including policy search, to the current database session."""
    clock = date.today() if today is None else today
    search = (
        retriever
        if retriever is not None
        else LocalKnowledgeRetriever(session, DeterministicEmbedding())
    )
    from assistflow_tools.writes import public_write_handlers

    bound = {
        "get_order": _order_handler(session, clock),
        "get_shipment": _shipment_handler(session, clock),
        "get_customer_profile": _profile_handler(session),
        "get_ticket": _ticket_handler(session),
        "search_support_policy": _policy_handler(search),
    }
    bound.update(public_write_handlers(session, today=clock))
    return bound


def _order_handler(session: Session, today: date) -> Handler:
    def handle(context: ToolContext, arguments: object) -> dict[str, object]:
        started = time.perf_counter()
        parsed = (
            arguments
            if isinstance(arguments, GetOrderArgs)
            else GetOrderArgs.model_validate(arguments)
        )
        if take_fault("get_order"):
            _command(context, "get_order", started, "tool_failed")
            raise ToolError("tool_failed", "The lookup failed.")
        try:
            order = _visible_order(session, context, parsed.order_id)
        except ToolError as exc:
            _command(context, "get_order", started, exc.code)
            raise
        shipment = ShipmentRepository(session).get_by_order(context.tenant_id, order.id)
        _command(context, "get_order", started, None)
        return project_order(order, shipment, today)

    return handle


def _shipment_handler(session: Session, today: date) -> Handler:
    def handle(context: ToolContext, arguments: object) -> dict[str, object]:
        if isinstance(arguments, GetShipmentArgs):
            parsed = arguments
        else:
            parsed = GetShipmentArgs.model_validate(arguments)
        order = _visible_order(session, context, parsed.order_id)
        shipment = ShipmentRepository(session).get_by_order(context.tenant_id, order.id)
        if shipment is None:
            raise ToolError("not_found", "That shipment was not found.")
        return project_shipment(order, shipment, today)

    return handle


def _profile_handler(session: Session) -> Handler:
    def handle(context: ToolContext, arguments: object) -> dict[str, object]:
        parsed = (
            arguments
            if isinstance(arguments, GetCustomerProfileArgs)
            else GetCustomerProfileArgs.model_validate(arguments)
        )
        if context.actor_type == "customer" and parsed.customer_id != context.customer_id:
            raise ToolError("denied", "That profile is not available.")
        customer = CustomerRepository(session).get(context.tenant_id, parsed.customer_id)
        if customer is None:
            raise ToolError("not_found", "That profile was not found.")
        return project_customer(customer)

    return handle


def _ticket_handler(session: Session) -> Handler:
    def handle(context: ToolContext, arguments: object) -> dict[str, object]:
        if isinstance(arguments, GetTicketArgs):
            parsed = arguments
        else:
            parsed = GetTicketArgs.model_validate(arguments)
        ticket = TicketRepository(session).get(context.tenant_id, parsed.ticket_id)
        if ticket is None:
            raise ToolError("not_found", "That ticket was not found.")
        if context.actor_type == "customer" and ticket.customer_id != context.customer_id:
            raise ToolError("not_found", "That ticket was not found.")
        return project_ticket(ticket)

    return handle


def _policy_handler(retriever: KnowledgeRetriever) -> Handler:
    def handle(context: ToolContext, arguments: object) -> dict[str, object]:
        parsed = (
            arguments
            if isinstance(arguments, SearchSupportPolicyArgs)
            else SearchSupportPolicyArgs.model_validate(arguments)
        )
        limit = min(DEFAULT_CHUNK_CAP, retriever.chunk_cap)
        started = time.perf_counter()
        found = retriever.retrieve(context.tenant_id, parsed.query, limit)
        record_hop(
            "retrieval",
            correlation_id=context.correlation_id,
            latency_ms=_elapsed_ms(started),
            tool_name="search_support_policy",
            status="succeeded",
            tenant_id=str(context.tenant_id),
            conversation_id=str(context.conversation_id),
        )
        return {
            "chunks": [
                {
                    "document_id": str(item.document_id),
                    "version": item.version,
                    "title": item.title,
                    "text": item.text,
                    "score": item.score,
                }
                for item in found
            ]
        }

    return handle


def _command(context: ToolContext, name: str, started: float, error_code: str | None) -> None:
    record_hop(
        "command",
        correlation_id=context.correlation_id,
        latency_ms=_elapsed_ms(started),
        tool_name=name,
        error_code=error_code,
        status="failed" if error_code else "succeeded",
        tenant_id=str(context.tenant_id),
        conversation_id=str(context.conversation_id),
    )


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


def _visible_order(session: Session, context: ToolContext, order_id: str) -> OrderRecord:
    found = _find_order(session, context.tenant_id, order_id)
    if found is None:
        raise ToolError("not_found", "That order was not found.")
    if context.actor_type == "customer" and found.customer_id != context.customer_id:
        raise ToolError("not_found", "That order was not found.")
    return found


def _find_order(session: Session, tenant_id: UUID, order_id: str) -> OrderRecord | None:
    repository = OrderRepository(session)
    try:
        parsed = UUID(order_id)
    except ValueError:
        return repository.get(tenant_id, order_id)
    return repository.get_by_id(tenant_id, parsed)
