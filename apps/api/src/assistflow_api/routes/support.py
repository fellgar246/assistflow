"""Read routes for the support simulator, plus ticket creation."""

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

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
from assistflow_customers.errors import SupportError
from assistflow_customers.repository import CustomerRepository
from assistflow_orders.repository import OrderRecord, OrderRepository
from assistflow_refunds.eligibility import check_refund
from assistflow_refunds.repository import RefundRepository
from assistflow_returns.eligibility import check_return
from assistflow_returns.repository import ReturnRepository
from assistflow_shipping.eligibility import check_address_change
from assistflow_shipping.repository import ShipmentRecord, ShipmentRepository
from assistflow_tickets.commands import create_ticket
from assistflow_tickets.repository import TicketRepository
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from assistflow_api.deps import PageQuery, correlation_id, get_session, page_query, require_tenant
from assistflow_api.present import present_customer, present_order, present_shipment, present_ticket
from assistflow_api.routes.conversations import require_open_conversation

router = APIRouter()

_ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": Problem},
    404: {"model": Problem},
    422: {"model": Problem},
}

TenantId = Annotated[UUID, Depends(require_tenant)]
Db = Annotated[Session, Depends(get_session)]
Page = Annotated[PageQuery, Depends(page_query)]


def _today() -> datetime:
    return datetime.now(UTC)


@router.get("/customers", response_model=CustomerPage, responses=_ERRORS)
def list_customers(tenant_id: TenantId, session: Db, page: Page) -> CustomerPage:
    listed = CustomerRepository(session).list(tenant_id, cursor=page.cursor, limit=page.limit)
    return CustomerPage(
        items=[present_customer(item) for item in listed.items],
        next_cursor=listed.next_cursor,
    )


@router.get("/customers/{customer_id}", response_model=Customer, responses=_ERRORS)
def read_customer(customer_id: UUID, tenant_id: TenantId, session: Db) -> Customer:
    return present_customer(CustomerRepository(session).require(tenant_id, customer_id))


@router.get("/orders", response_model=OrderPage, responses=_ERRORS)
def list_orders(tenant_id: TenantId, session: Db, page: Page) -> OrderPage:
    listed = OrderRepository(session).list(tenant_id, cursor=page.cursor, limit=page.limit)
    shipments = ShipmentRepository(session)
    today = _today().date()
    items = [
        present_order(order, shipments.get_by_order(tenant_id, order.id), today)
        for order in listed.items
    ]
    return OrderPage(items=items, next_cursor=listed.next_cursor)


@router.get("/orders/{order_number}", response_model=Order, responses=_ERRORS)
def read_order(order_number: str, tenant_id: TenantId, session: Db) -> Order:
    order, shipment = _order_shipment(session, tenant_id, order_number)
    return present_order(order, shipment, _today().date())


@router.get("/orders/{order_number}/shipment", response_model=Shipment, responses=_ERRORS)
def read_shipment(order_number: str, tenant_id: TenantId, session: Db) -> Shipment:
    order, shipment = _order_shipment(session, tenant_id, order_number)
    if shipment is None:
        raise SupportError(
            "shipment_not_found",
            f"Shipment for order {order_number} was not found.",
            404,
        )
    return present_shipment(order, shipment, _today().date())


@router.get(
    "/orders/{order_number}/eligibility/address-change",
    response_model=Eligibility,
    responses=_ERRORS,
)
def read_address_change_eligibility(
    order_number: str, tenant_id: TenantId, session: Db
) -> Eligibility:
    order, shipment = _order_shipment(session, tenant_id, order_number)
    return check_address_change(
        order.status,
        None if shipment is None else shipment.status,
        None if shipment is None else shipment.estimated_delivery_on,
        _today().date(),
    )


@router.get(
    "/orders/{order_number}/eligibility/return",
    response_model=ReturnEligibility,
    responses=_ERRORS,
)
def read_return_eligibility(
    order_number: str, tenant_id: TenantId, session: Db
) -> ReturnEligibility:
    order, shipment = _order_shipment(session, tenant_id, order_number)
    shipped_on = None
    if shipment is not None and shipment.shipped_at is not None:
        shipped_on = shipment.shipped_at.date()
    return check_return(
        order_status=order.status,
        shipment_status=None if shipment is None else shipment.status,
        estimated_delivery_on=None if shipment is None else shipment.estimated_delivery_on,
        shipped_on=shipped_on,
        has_open_return=ReturnRepository(session).has_open_return(tenant_id, order.id),
        today=_today().date(),
    )


@router.get(
    "/orders/{order_number}/eligibility/refund",
    response_model=RefundEligibility,
    responses=_ERRORS,
)
def read_refund_eligibility(
    order_number: str, tenant_id: TenantId, session: Db
) -> RefundEligibility:
    order = OrderRepository(session).require(tenant_id, order_number)
    return check_refund(
        order_status=order.status,
        total_cents=order.total_cents,
        reserved_cents=RefundRepository(session).reserved_cents(tenant_id, order.id),
        currency=order.currency,
    )


@router.get("/tickets", response_model=TicketPage, responses=_ERRORS)
def list_tickets(tenant_id: TenantId, session: Db, page: Page) -> TicketPage:
    listed = TicketRepository(session).list(tenant_id, cursor=page.cursor, limit=page.limit)
    return TicketPage(
        items=[present_ticket(item) for item in listed.items],
        next_cursor=listed.next_cursor,
    )


@router.get("/tickets/{ticket_id}", response_model=Ticket, responses=_ERRORS)
def read_ticket(ticket_id: UUID, tenant_id: TenantId, session: Db) -> Ticket:
    return present_ticket(TicketRepository(session).require(tenant_id, ticket_id))


@router.post("/tickets", response_model=Ticket, status_code=201, responses=_ERRORS)
def post_ticket(
    body: TicketCreate,
    response: Response,
    tenant_id: TenantId,
    session: Db,
    correlation: Annotated[str, Depends(correlation_id)],
) -> Ticket:
    if body.conversation_id is not None:
        require_open_conversation(session, tenant_id, body.customer_id, body.conversation_id)
    result = create_ticket(
        session,
        tenant_id,
        body.customer_id,
        body.priority,
        body.category,
        body.summary,
        body.idempotency_key,
        conversation_id=body.conversation_id,
        correlation_id=correlation,
        actor_type="customer",
        actor_id=body.customer_id,
    )
    response.headers["X-Correlation-Id"] = correlation
    if result.replayed:
        response.status_code = 200
    return result.ticket


def _order_shipment(
    session: Session, tenant_id: UUID, order_number: str
) -> tuple[OrderRecord, ShipmentRecord | None]:
    order = OrderRepository(session).require(tenant_id, order_number)
    shipment = ShipmentRepository(session).get_by_order(tenant_id, order.id)
    return order, shipment
