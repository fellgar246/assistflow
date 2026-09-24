"""Refund eligibility. This function does not read or write rows."""

from assistflow_contracts.support import OrderStatus, RefundEligibility

_REFUNDABLE = {OrderStatus.PAID, OrderStatus.FULFILLED}


def check_refund(
    order_status: OrderStatus,
    total_cents: int,
    reserved_cents: int,
    currency: str,
) -> RefundEligibility:
    """Return the remaining refund cap. The result never names a payment instrument."""
    if order_status is OrderStatus.CANCELLED:
        return _decision(False, "order_cancelled", 0, currency)
    if order_status not in _REFUNDABLE:
        return _decision(False, "order_not_paid", 0, currency)
    reserved = max(reserved_cents, 0)
    remaining = max(min(total_cents, total_cents - reserved), 0)
    if remaining == 0:
        return _decision(False, "nothing_to_refund", 0, currency)
    return _decision(True, "eligible", remaining, currency)


def _decision(
    eligible: bool, reason_code: str, maximum_amount_cents: int, currency: str
) -> RefundEligibility:
    return RefundEligibility(
        eligible=eligible,
        reason_code=reason_code,
        maximum_amount_cents=maximum_amount_cents,
        currency=currency,
    )
