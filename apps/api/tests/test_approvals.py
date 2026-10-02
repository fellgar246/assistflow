"""Sensitive changes wait for a matching, unexpired confirmation."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from assistflow_conversations.models import ApprovalRequestRow, AuditEventRow
from assistflow_orders.repository import OrderRepository
from assistflow_refunds.models import RefundRequestRow
from assistflow_returns.models import ReturnRequestRow
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
FIELDLINE = UUID("22222222-2222-4222-8222-222222222222")
HARBOR_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001")
FIELDLINE_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0002")
ORDER = "ORD-10482"
RETURN_ORDER = "ORD-20817"


def test_address_change_waits_until_confirm_and_does_not_repeat(
    support_client: TestClient, support_engine: Engine
) -> None:
    conversation_id = _open(support_client)
    before = _line1(support_engine)
    asked = support_client.post(
        f"/conversations/{conversation_id}/messages",
        headers=_headers(support_client),
        json={
            "content": (
                "Please change the delivery address for ORD-10482\n"
                "recipient: Ava Chen\n"
                "line1: 42 Congress Avenue\n"
                "city: Austin\n"
                "region: TX\n"
                "postal_code: 78701\n"
                "country: US"
            ),
            "idempotency_key": "msg-address-1",
        },
    )
    assert asked.status_code == 201
    conversation = support_client.get(
        f"/conversations/{conversation_id}",
        headers=_headers(support_client),
    )
    transcript = support_client.get(
        f"/conversations/{conversation_id}/messages",
        headers=_headers(support_client),
    )
    approval = _approval(transcript.json())
    change = approval["proposed_change"]

    assert conversation.json()["status"] == "waiting_approval"
    assert approval["status"] == "pending"
    assert change["kind"] == "address"
    assert change["current"]["line1"] == "18 Market Street"
    assert change["proposed"]["line1"] == "42 Congress Avenue"
    assert "arguments" not in approval
    assert _line1(support_engine) == before
    assert _actions(support_engine) >= {"approval.requested"}

    confirmed = support_client.post(
        f"/conversations/{conversation_id}/approvals/{approval['id']}/confirm",
        headers=_headers(support_client, "confirm-1"),
        json={},
    )
    again = support_client.post(
        f"/conversations/{conversation_id}/approvals/{approval['id']}/confirm",
        headers=_headers(support_client, "confirm-2"),
        json={},
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "consumed"
    assert again.status_code == 200
    assert again.json()["status"] == "consumed"
    assert again.json()["id"] == confirmed.json()["id"]
    assert _line1(support_engine) == "42 Congress Avenue"
    assert _actions(support_engine) >= {"approval.approved", "approval.consumed"}
    assert _count(support_engine, "shipping") == 1


def test_confirm_ignores_a_client_supplied_address(
    support_client: TestClient, support_engine: Engine
) -> None:
    conversation_id = _open(support_client)
    approval = _propose_address(support_client, conversation_id)
    before = _line1(support_engine)
    rejected = support_client.post(
        f"/conversations/{conversation_id}/approvals/{approval['id']}/confirm",
        headers=_headers(support_client),
        json={
            "new_address": {
                "recipient": "Someone Else",
                "line1": "1 Other Street",
                "city": "Dallas",
                "region": "TX",
                "postal_code": "75201",
                "country": "US",
            }
        },
    )

    assert rejected.status_code == 422
    assert _line1(support_engine) == before
    assert _stored_status(support_engine, approval["id"]) == "pending"


def test_expired_confirm_does_not_change_the_address(
    support_client: TestClient, support_engine: Engine
) -> None:
    conversation_id = _open(support_client)
    approval = _propose_address(support_client, conversation_id)
    before = _line1(support_engine)
    _expire(support_engine, approval["id"])
    confirmed = support_client.post(
        f"/conversations/{conversation_id}/approvals/{approval['id']}/confirm",
        headers=_headers(support_client),
        json={},
    )

    assert confirmed.status_code == 409
    assert confirmed.json()["code"] == "approval_expired"
    assert _line1(support_engine) == before
    assert _stored_status(support_engine, approval["id"]) == "expired"
    assert "approval.expired" in _actions(support_engine)


def test_hash_mismatch_denies_execution(support_client: TestClient, support_engine: Engine) -> None:
    conversation_id = _open(support_client)
    approval = _propose_address(support_client, conversation_id)
    before = _line1(support_engine)
    with Session(support_engine) as session:
        row = session.get(ApprovalRequestRow, UUID(approval["id"]))
        assert row is not None
        raw_arguments = row.arguments
        assert isinstance(raw_arguments, dict)
        edited = dict(raw_arguments)
        raw_address = edited["new_address"]
        assert isinstance(raw_address, dict)
        address = dict(raw_address)
        address["line1"] = "9 Other Road"
        edited["new_address"] = address
        row.arguments = edited
        session.commit()
    confirmed = support_client.post(
        f"/conversations/{conversation_id}/approvals/{approval['id']}/confirm",
        headers=_headers(support_client),
        json={},
    )

    assert confirmed.status_code == 409
    assert confirmed.json()["code"] == "approval_hash_mismatch"
    assert _line1(support_engine) == before
    assert _stored_status(support_engine, approval["id"]) == "pending"


def test_cancel_leaves_the_address_unchanged(
    support_client: TestClient, support_engine: Engine
) -> None:
    conversation_id = _open(support_client)
    approval = _propose_address(support_client, conversation_id)
    before = _line1(support_engine)
    cancelled = support_client.post(
        f"/conversations/{conversation_id}/approvals/{approval['id']}/reject",
        headers=_headers(support_client),
        json={},
    )
    conversation = support_client.get(
        f"/conversations/{conversation_id}",
        headers=_headers(support_client),
    )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "rejected"
    assert _line1(support_engine) == before
    assert conversation.json()["status"] == "open"
    assert "approval.rejected" in _actions(support_engine)


def test_another_customer_cannot_confirm(
    support_client: TestClient, support_engine: Engine
) -> None:
    conversation_id = _open(support_client)
    approval = _propose_address(support_client, conversation_id)
    before = _line1(support_engine)
    denied = support_client.post(
        f"/conversations/{conversation_id}/approvals/{approval['id']}/confirm",
        headers=_headers(support_client, tenant=FIELDLINE, customer=FIELDLINE_CUSTOMER),
        json={},
    )

    assert denied.status_code == 404
    assert _line1(support_engine) == before


def test_refund_and_return_use_the_same_confirmation(
    support_client: TestClient, support_engine: Engine
) -> None:
    refund_conversation = _open(support_client)
    refund_approval = _propose(
        support_client,
        refund_conversation,
        "Please refund ORD-10482\namount_cents: 1500\nreason: damaged",
        "msg-refund",
    )
    refund_change = refund_approval["proposed_change"]
    assert refund_change["kind"] == "refund"
    assert refund_change["amount_cents"] == 1500
    assert refund_change["currency"] == "USD"
    assert "card" not in str(refund_change).lower()
    confirmed = support_client.post(
        f"/conversations/{refund_conversation}/approvals/{refund_approval['id']}/confirm",
        headers=_headers(support_client),
        json={},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "consumed"
    assert _count_rows(support_engine, RefundRequestRow) == 1

    return_conversation = _open(
        support_client, tenant=FIELDLINE, customer=FIELDLINE_CUSTOMER, key="open-return"
    )
    return_approval = _propose(
        support_client,
        return_conversation,
        "I want to start a return for ORD-20817\nreason: damaged",
        "msg-return",
        tenant=FIELDLINE,
        customer=FIELDLINE_CUSTOMER,
    )
    assert return_approval["proposed_change"]["kind"] == "return"
    assert return_approval["proposed_change"]["reason_label"] == "Damaged"
    started = support_client.post(
        f"/conversations/{return_conversation}/approvals/{return_approval['id']}/confirm",
        headers=_headers(support_client, tenant=FIELDLINE, customer=FIELDLINE_CUSTOMER),
        json={},
    )
    assert started.status_code == 200
    assert _count_rows(support_engine, ReturnRequestRow) == 1


def _open(
    client: TestClient,
    *,
    tenant: UUID = HARBOR,
    customer: UUID = HARBOR_CUSTOMER,
    key: str = "open-approval",
) -> str:
    created = client.post(
        "/conversations",
        headers=_headers(client, tenant=tenant, customer=customer),
        json={"idempotency_key": key},
    )
    assert created.status_code == 201
    return str(created.json()["id"])


def _propose_address(client: TestClient, conversation_id: str) -> dict[str, Any]:
    return _propose(
        client,
        conversation_id,
        "Please update the delivery address for ORD-10482",
        "msg-address-default",
    )


def _propose(
    client: TestClient,
    conversation_id: str,
    content: str,
    key: str,
    *,
    tenant: UUID = HARBOR,
    customer: UUID = HARBOR_CUSTOMER,
) -> dict[str, Any]:
    posted = client.post(
        f"/conversations/{conversation_id}/messages",
        headers=_headers(client, tenant=tenant, customer=customer),
        json={"content": content, "idempotency_key": key},
    )
    assert posted.status_code == 201, posted.text
    transcript = client.get(
        f"/conversations/{conversation_id}/messages",
        headers=_headers(client, tenant=tenant, customer=customer),
    )
    assert transcript.status_code == 200
    return _approval(transcript.json())


def _approval(page: dict[str, Any]) -> dict[str, Any]:
    items = page["items"]
    assert isinstance(items, list)
    for item in items:
        assert isinstance(item, dict)
        approvals = item.get("approvals")
        if isinstance(approvals, list) and approvals:
            approval = approvals[0]
            assert isinstance(approval, dict)
            return approval
    raise AssertionError("expected an approval card")


def _headers(
    client: TestClient,
    correlation: str = "corr-approval",
    *,
    tenant: UUID = HARBOR,
    customer: UUID = HARBOR_CUSTOMER,
) -> dict[str, str]:
    from tokens import customer_headers

    return customer_headers(client, tenant, customer, correlation)


def _line1(engine: Engine) -> str:
    with Session(engine) as session:
        return OrderRepository(session).require(HARBOR, ORDER).shipping_address.line1


def _stored_status(engine: Engine, approval_id: str) -> str:
    with Session(engine) as session:
        row = session.get(ApprovalRequestRow, UUID(approval_id))
        assert row is not None
        return row.status


def _expire(engine: Engine, approval_id: str) -> None:
    with Session(engine) as session:
        row = session.get(ApprovalRequestRow, UUID(approval_id))
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        session.commit()


def _actions(engine: Engine) -> set[str]:
    with Session(engine) as session:
        rows = session.scalars(select(AuditEventRow.action)).all()
        return set(rows)


def _count(engine: Engine, action_prefix: str) -> int:
    with Session(engine) as session:
        rows = session.scalars(select(AuditEventRow.action)).all()
        return sum(1 for action in rows if action.startswith(action_prefix))


def _count_rows(engine: Engine, model: type[RefundRequestRow] | type[ReturnRequestRow]) -> int:
    with Session(engine) as session:
        counted = session.scalar(select(func.count()).select_from(model))
        return int(counted or 0)
