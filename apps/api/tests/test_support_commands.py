"""In-process return and refund commands."""

from datetime import date
from uuid import UUID

import pytest
from assistflow_customers.errors import SupportError
from assistflow_refunds.commands import RefundWrite, create_refund_request
from assistflow_refunds.models import RefundRequestRow
from assistflow_returns.commands import create_return_request
from assistflow_returns.models import ReturnRequestRow
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
FIELDLINE = UUID("22222222-2222-4222-8222-222222222222")


def test_in_transit_order_cannot_be_returned(support_engine: Engine) -> None:
    with Session(support_engine) as session:
        with pytest.raises(SupportError) as caught:
            create_return_request(
                session,
                HARBOR,
                "ORD-10482",
                "damaged",
                "return-1",
                today=date(2026, 9, 23),
            )
        session.rollback()

    assert caught.value.code == "not_delivered"


def test_return_command_is_idempotent_for_a_delivered_order(support_engine: Engine) -> None:
    with Session(support_engine) as session:
        first = create_return_request(
            session,
            FIELDLINE,
            "ORD-20817",
            "changed_mind",
            "return-1",
            today=date(2026, 9, 23),
        )
        second = create_return_request(
            session,
            FIELDLINE,
            "ORD-20817",
            "changed_mind",
            "return-1",
            today=date(2026, 9, 23),
        )
        with pytest.raises(SupportError) as caught:
            create_return_request(
                session,
                FIELDLINE,
                "ORD-20817",
                "damaged",
                "return-2",
                today=date(2026, 9, 23),
            )
        count = session.scalar(select(func.count()).select_from(ReturnRequestRow))
        session.commit()

    assert first.id == second.id
    assert second.replayed is True
    assert first.status.value == "requested"
    assert caught.value.code == "return_already_open"
    assert count == 1


def test_return_outside_the_window_is_rejected(support_engine: Engine) -> None:
    with Session(support_engine) as session, pytest.raises(SupportError) as caught:
        create_return_request(
            session,
            FIELDLINE,
            "ORD-20817",
            "damaged",
            "return-late",
            today=date(2026, 11, 1),
        )

    assert caught.value.code == "return_window_closed"


def test_refund_command_replays_and_never_records_a_payment(support_engine: Engine) -> None:
    with Session(support_engine) as session:
        first = create_refund_request(session, HARBOR, "ORD-10482", 1000, "refund-1")
        second = create_refund_request(session, HARBOR, "ORD-10482", 1000, "refund-1")
        with pytest.raises(SupportError) as conflict:
            create_refund_request(session, HARBOR, "ORD-10482", 50, "refund-1")
        with pytest.raises(SupportError) as too_much:
            create_refund_request(session, HARBOR, "ORD-10482", 5000, "refund-2")
        count = session.scalar(select(func.count()).select_from(RefundRequestRow))
        session.commit()

    assert first.id == second.id
    assert second.replayed is True
    assert first.status.value == "requested"
    assert first.amount_cents == 1000
    assert first.currency == "USD"
    assert conflict.value.code == "idempotency_conflict"
    assert too_much.value.code == "amount_exceeds_maximum"
    assert count == 1
    assert "payment" not in RefundWrite.__dataclass_fields__
    assert "instrument" not in RefundWrite.__dataclass_fields__


def test_refund_check_sees_the_reserved_amount(
    support_engine: Engine, support_client: TestClient
) -> None:
    with Session(support_engine) as session:
        create_refund_request(session, HARBOR, "ORD-10482", 1000, "refund-1")
        session.commit()

    from tokens import authorization

    response = support_client.get(
        "/orders/ORD-10482/eligibility/refund",
        headers=authorization(support_client, "ava-chen"),
    )

    assert response.status_code == 200
    assert response.json()["maximum_amount_cents"] == 3599
    assert "payment" not in response.text.lower()
