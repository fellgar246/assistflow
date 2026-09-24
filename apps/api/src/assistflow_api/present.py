"""Map stored records to customer-facing payloads."""

from datetime import date

from assistflow_contracts.support import (
    Customer,
    Order,
    Shipment,
    ShipmentSummary,
    Ticket,
)
from assistflow_customers.repository import CustomerRecord
from assistflow_orders.repository import OrderRecord
from assistflow_shipping.eligibility import check_address_change
from assistflow_shipping.repository import ShipmentRecord
from assistflow_tickets.repository import TicketRecord


def present_customer(record: CustomerRecord) -> Customer:
    return Customer(
        id=record.id,
        email=record.email,
        display_name=record.display_name,
        status=record.status,
        created_at=record.created_at,
    )


def present_ticket(record: TicketRecord) -> Ticket:
    return Ticket(
        id=record.id,
        priority=record.priority,
        category=record.category,
        status=record.status,
        summary=record.summary,
        conversation_id=record.conversation_id,
        created_at=record.created_at,
    )


def present_shipment(order: OrderRecord, shipment: ShipmentRecord, today: date) -> Shipment:
    summary = _summary(order, shipment, today)
    return Shipment(order_number=order.order_number, **summary.model_dump())


def present_order(order: OrderRecord, shipment: ShipmentRecord | None, today: date) -> Order:
    nested = None if shipment is None else _summary(order, shipment, today)
    return Order(
        order_number=order.order_number,
        status=order.status,
        currency=order.currency,
        total_cents=order.total_cents,
        shipping_address=order.shipping_address,
        created_at=order.created_at,
        shipment=nested,
    )


def _summary(order: OrderRecord, shipment: ShipmentRecord, today: date) -> ShipmentSummary:
    decision = check_address_change(
        order.status,
        shipment.status,
        shipment.estimated_delivery_on,
        today,
    )
    return ShipmentSummary(
        carrier_name=shipment.carrier_name,
        status=shipment.status,
        origin_hub=shipment.origin_hub,
        estimated_delivery_on=shipment.estimated_delivery_on,
        address_change_eligible=decision.eligible,
        shipped_at=shipment.shipped_at,
    )
