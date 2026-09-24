"""Table-driven eligibility rules."""

from datetime import date

import pytest
from assistflow_contracts.support import OrderStatus, ShipmentStatus
from assistflow_refunds.eligibility import check_refund
from assistflow_returns.eligibility import check_return
from assistflow_shipping.eligibility import check_address_change


@pytest.mark.parametrize(
    ("order_status", "shipment_status", "delivery", "today", "eligible", "reason"),
    [
        (
            OrderStatus.FULFILLED,
            ShipmentStatus.IN_TRANSIT,
            date(2099, 6, 15),
            date(2026, 9, 23),
            True,
            "eligible",
        ),
        (
            OrderStatus.PAID,
            ShipmentStatus.PENDING,
            None,
            date(2026, 9, 23),
            True,
            "eligible",
        ),
        (
            OrderStatus.FULFILLED,
            ShipmentStatus.OUT_FOR_DELIVERY,
            date(2026, 9, 23),
            date(2026, 9, 23),
            True,
            "eligible",
        ),
        (
            OrderStatus.FULFILLED,
            ShipmentStatus.DELIVERED,
            date(2099, 6, 15),
            date(2026, 9, 23),
            False,
            "already_delivered",
        ),
        (
            OrderStatus.FULFILLED,
            ShipmentStatus.EXCEPTION,
            date(2099, 6, 15),
            date(2026, 9, 23),
            False,
            "shipment_exception",
        ),
        (
            OrderStatus.FULFILLED,
            ShipmentStatus.IN_TRANSIT,
            date(2026, 9, 1),
            date(2026, 9, 23),
            False,
            "cutoff_passed",
        ),
        (
            OrderStatus.CANCELLED,
            ShipmentStatus.IN_TRANSIT,
            date(2099, 6, 15),
            date(2026, 9, 23),
            False,
            "order_cancelled",
        ),
        (OrderStatus.FULFILLED, None, None, date(2026, 9, 23), False, "shipment_not_found"),
    ],
)
def test_address_change_rules(
    order_status: OrderStatus,
    shipment_status: ShipmentStatus | None,
    delivery: date | None,
    today: date,
    eligible: bool,
    reason: str,
) -> None:
    decision = check_address_change(order_status, shipment_status, delivery, today)

    assert decision.eligible is eligible
    assert decision.reason_code == reason


@pytest.mark.parametrize(
    ("order_status", "shipment_status", "delivery", "shipped_on", "open_return", "today", "reason"),
    [
        (
            OrderStatus.FULFILLED,
            ShipmentStatus.DELIVERED,
            date(2026, 9, 10),
            date(2026, 9, 9),
            False,
            date(2026, 9, 23),
            "eligible",
        ),
        (
            OrderStatus.PAID,
            ShipmentStatus.DELIVERED,
            date(2026, 9, 1),
            None,
            False,
            date(2026, 10, 1),
            "eligible",
        ),
        (
            OrderStatus.FULFILLED,
            ShipmentStatus.IN_TRANSIT,
            date(2099, 6, 15),
            date(2026, 9, 2),
            False,
            date(2026, 9, 23),
            "not_delivered",
        ),
        (
            OrderStatus.FULFILLED,
            ShipmentStatus.DELIVERED,
            date(2026, 8, 1),
            None,
            False,
            date(2026, 9, 23),
            "return_window_closed",
        ),
        (
            OrderStatus.FULFILLED,
            ShipmentStatus.DELIVERED,
            date(2026, 9, 10),
            None,
            True,
            date(2026, 9, 23),
            "return_already_open",
        ),
        (
            OrderStatus.CANCELLED,
            ShipmentStatus.DELIVERED,
            date(2026, 9, 10),
            None,
            False,
            date(2026, 9, 23),
            "order_cancelled",
        ),
        (
            OrderStatus.PLACED,
            ShipmentStatus.DELIVERED,
            date(2026, 9, 10),
            None,
            False,
            date(2026, 9, 23),
            "order_not_fulfilled",
        ),
    ],
)
def test_return_rules(
    order_status: OrderStatus,
    shipment_status: ShipmentStatus | None,
    delivery: date | None,
    shipped_on: date | None,
    open_return: bool,
    today: date,
    reason: str,
) -> None:
    decision = check_return(
        order_status,
        shipment_status,
        delivery,
        shipped_on,
        open_return,
        today,
    )

    assert decision.reason_code == reason
    assert decision.eligible is (reason == "eligible")
    assert decision.allowed_reason_codes == [
        "damaged",
        "wrong_item",
        "not_as_described",
        "changed_mind",
        "other",
    ]


@pytest.mark.parametrize(
    ("order_status", "total", "reserved", "eligible", "reason", "maximum"),
    [
        (OrderStatus.PAID, 4599, 0, True, "eligible", 4599),
        (OrderStatus.FULFILLED, 4599, 1000, True, "eligible", 3599),
        (OrderStatus.FULFILLED, 4599, 4599, False, "nothing_to_refund", 0),
        (OrderStatus.PAID, 4599, 9000, False, "nothing_to_refund", 0),
        (OrderStatus.PLACED, 4599, 0, False, "order_not_paid", 0),
        (OrderStatus.CANCELLED, 4599, 0, False, "order_cancelled", 0),
    ],
)
def test_refund_rules(
    order_status: OrderStatus,
    total: int,
    reserved: int,
    eligible: bool,
    reason: str,
    maximum: int,
) -> None:
    decision = check_refund(order_status, total, reserved, "USD")
    payload = decision.model_dump()

    assert decision.eligible is eligible
    assert decision.reason_code == reason
    assert decision.maximum_amount_cents == maximum
    assert decision.maximum_amount_cents <= total
    assert decision.currency == "USD"
    assert "payment" not in payload
    assert "instrument" not in payload
    assert "card" not in payload
