"""Return eligibility. This function does not read or write rows."""

from datetime import date, timedelta

from assistflow_contracts.support import (
    RETURN_REASON_CODES,
    OrderStatus,
    ReturnEligibility,
    ShipmentStatus,
)

_RETURNABLE_ORDERS = {OrderStatus.PAID, OrderStatus.FULFILLED}
_WINDOW_DAYS = 30


def check_return(
    order_status: OrderStatus,
    shipment_status: ShipmentStatus | None,
    estimated_delivery_on: date | None,
    shipped_on: date | None,
    has_open_return: bool,
    today: date,
) -> ReturnEligibility:
    """Return whether a new return request is allowed, plus the closed reason list."""
    allowed = list(RETURN_REASON_CODES)
    if order_status is OrderStatus.CANCELLED:
        return ReturnEligibility(
            eligible=False, reason_code="order_cancelled", allowed_reason_codes=allowed
        )
    if order_status not in _RETURNABLE_ORDERS:
        return ReturnEligibility(
            eligible=False, reason_code="order_not_fulfilled", allowed_reason_codes=allowed
        )
    if has_open_return:
        return ReturnEligibility(
            eligible=False, reason_code="return_already_open", allowed_reason_codes=allowed
        )
    if shipment_status is not ShipmentStatus.DELIVERED:
        return ReturnEligibility(
            eligible=False, reason_code="not_delivered", allowed_reason_codes=allowed
        )
    anchor = estimated_delivery_on or shipped_on
    if anchor is None or today > anchor + timedelta(days=_WINDOW_DAYS):
        return ReturnEligibility(
            eligible=False, reason_code="return_window_closed", allowed_reason_codes=allowed
        )
    return ReturnEligibility(eligible=True, reason_code="eligible", allowed_reason_codes=allowed)
