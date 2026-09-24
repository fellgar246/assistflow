"""Safe fields returned to the assistant. Secrets and payment data are omitted."""

from datetime import date
from typing import Any

from assistflow_customers.repository import CustomerRecord
from assistflow_orders.repository import OrderRecord
from assistflow_shipping.eligibility import check_address_change
from assistflow_shipping.repository import ShipmentRecord
from assistflow_tickets.repository import TicketRecord

from assistflow_tools.models import FORBIDDEN_KEY_MARKERS


def project_order(
    order: OrderRecord, shipment: ShipmentRecord | None, today: date
) -> dict[str, Any]:
    """Order facts a customer may see. Street address and other customers stay out."""
    body: dict[str, Any] = {
        "order_id": order.order_number,
        "status": order.status.value,
        "created_at": order.created_at.isoformat(),
        "total_cents": order.total_cents,
        "currency": order.currency,
        "shipping_city": order.shipping_address.city,
        "shipping_country": order.shipping_address.country,
        "shipment": None if shipment is None else project_shipment(order, shipment, today),
    }
    return safe_body(body)


def project_shipment(order: OrderRecord, shipment: ShipmentRecord, today: date) -> dict[str, Any]:
    """Carrier label and delivery facts. No carrier credentials."""
    decision = check_address_change(
        order.status,
        shipment.status,
        shipment.estimated_delivery_on,
        today,
    )
    delivery = shipment.estimated_delivery_on
    return safe_body(
        {
            "order_id": order.order_number,
            "carrier_name": shipment.carrier_name,
            "status": shipment.status.value,
            "origin_hub": shipment.origin_hub,
            "estimated_delivery_on": None if delivery is None else delivery.isoformat(),
            "address_change_eligible": decision.eligible,
        }
    )


def project_customer(customer: CustomerRecord) -> dict[str, Any]:
    """Display name, email, and status. No secrets and no payment instruments."""
    return safe_body(
        {
            "customer_id": str(customer.id),
            "display_name": customer.display_name,
            "email": customer.email,
            "status": customer.status.value,
        }
    )


def project_ticket(ticket: TicketRecord) -> dict[str, Any]:
    """Ticket status and a short summary. Free-form notes are not included."""
    return safe_body(
        {
            "ticket_id": str(ticket.id),
            "status": ticket.status.value,
            "priority": ticket.priority.value,
            "category": ticket.category.value,
            "summary": ticket.summary[:240],
            "created_at": ticket.created_at.isoformat(),
        }
    )


def safe_body(body: dict[str, Any]) -> dict[str, Any]:
    """Drop keys that must never leave a read tool."""
    cleaned: dict[str, Any] = {}
    for key, value in body.items():
        if _forbidden(key):
            continue
        if isinstance(value, dict):
            cleaned[key] = safe_body(value)
        else:
            cleaned[key] = value
    return cleaned


def contains_forbidden_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            _forbidden(str(key)) or contains_forbidden_key(item) for key, item in value.items()
        )
    if isinstance(value, list):
        return any(contains_forbidden_key(item) for item in value)
    return False


def _forbidden(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in FORBIDDEN_KEY_MARKERS)
