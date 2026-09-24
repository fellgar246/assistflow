"""Address-change eligibility. This function does not read or write rows."""

from datetime import date

from assistflow_contracts.support import Eligibility, OrderStatus, ShipmentStatus

_OPEN_STATUSES = {
    ShipmentStatus.PENDING,
    ShipmentStatus.IN_TRANSIT,
    ShipmentStatus.OUT_FOR_DELIVERY,
}


def check_address_change(
    order_status: OrderStatus,
    shipment_status: ShipmentStatus | None,
    estimated_delivery_on: date | None,
    today: date,
) -> Eligibility:
    """Return whether an address change is still inside the cutoff."""
    if order_status is OrderStatus.CANCELLED:
        return Eligibility(eligible=False, reason_code="order_cancelled")
    if shipment_status is None:
        return Eligibility(eligible=False, reason_code="shipment_not_found")
    if shipment_status is ShipmentStatus.DELIVERED:
        return Eligibility(eligible=False, reason_code="already_delivered")
    if shipment_status is ShipmentStatus.EXCEPTION:
        return Eligibility(eligible=False, reason_code="shipment_exception")
    if shipment_status not in _OPEN_STATUSES:
        return Eligibility(eligible=False, reason_code="shipment_not_eligible")
    if estimated_delivery_on is not None and estimated_delivery_on < today:
        return Eligibility(eligible=False, reason_code="cutoff_passed")
    return Eligibility(eligible=True, reason_code="eligible")
