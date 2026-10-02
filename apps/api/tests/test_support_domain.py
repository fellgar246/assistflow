"""Acceptance coverage for tenant-scoped support reads."""

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from assistflow_contracts.support import OrderStatus, ShippingAddress
from assistflow_customers.errors import SupportError
from assistflow_orders.repository import OrderRecord, OrderRepository
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from assistflow_api.config import repo_root
from assistflow_api.seed import fixture_path, seed_support_domain
from tokens import authorization

HARBOR = "ORD-10482"
FIELDLINE = "ORD-20817"


def _document() -> dict[str, Any]:
    loaded = json.loads(fixture_path().read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise AssertionError("fixture must be an object")
    return cast(dict[str, Any], loaded)


def _tenant_for(order_number: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for tenant in _document()["tenants"]:
        if not isinstance(tenant, dict):
            continue
        for order in tenant["orders"]:
            if isinstance(order, dict) and order["order_number"] == order_number:
                return tenant, order
    raise AssertionError(order_number)


def _headers(client: TestClient, order_number: str) -> dict[str, str]:
    user = "ben-ortiz" if order_number == FIELDLINE else "ava-chen"
    return authorization(client, user)


def test_known_order_matches_the_fixture_and_is_stable(support_client: TestClient) -> None:
    _tenant, order = _tenant_for(HARBOR)
    shipment = order["shipment"]

    first = support_client.get(f"/orders/{HARBOR}", headers=_headers(support_client, HARBOR))
    second = support_client.get(f"/orders/{HARBOR}", headers=_headers(support_client, HARBOR))

    assert first.status_code == 200
    assert first.json() == second.json()
    body = first.json()
    assert body["order_number"] == HARBOR
    assert body["status"] == order["status"]
    assert body["currency"] == order["currency"]
    assert body["total_cents"] == order["total_cents"]
    assert body["shipping_address"] == order["shipping_address"]
    assert body["created_at"] == "2026-09-01T15:00:00Z"
    assert body["shipment"]["origin_hub"] == shipment["origin_hub"]
    assert body["shipment"]["estimated_delivery_on"] == shipment["estimated_delivery_on"]
    assert body["shipment"]["status"] == shipment["status"]
    assert body["shipment"]["carrier_name"] == shipment["carrier_name"]
    assert body["shipment"]["address_change_eligible"] is True
    assert "id" not in body
    assert "tenant_id" not in body


def test_unknown_order_is_not_found(support_client: TestClient) -> None:
    response = support_client.get("/orders/ORD-99999", headers=_headers(support_client, HARBOR))

    assert response.status_code == 404
    assert response.json() == {
        "code": "order_not_found",
        "message": "Order ORD-99999 was not found.",
    }
    assert "traceback" not in response.text.lower()


def test_other_tenant_cannot_read_or_list_the_order(support_client: TestClient) -> None:
    hidden = support_client.get(f"/orders/{HARBOR}", headers=_headers(support_client, FIELDLINE))
    listed = support_client.get("/orders", headers=_headers(support_client, FIELDLINE))

    assert hidden.status_code == 404
    assert hidden.json()["code"] == "order_not_found"
    assert "DFW" not in hidden.text
    assert "Ava" not in hidden.text
    assert [item["order_number"] for item in listed.json()["items"]] == [FIELDLINE]


def test_seeded_eligibility_checks(support_client: TestClient) -> None:
    address = support_client.get(
        f"/orders/{HARBOR}/eligibility/address-change",
        headers=_headers(support_client, HARBOR),
    )
    delivered = support_client.get(
        f"/orders/{FIELDLINE}/eligibility/address-change",
        headers=_headers(support_client, FIELDLINE),
    )
    returns = support_client.get(
        f"/orders/{HARBOR}/eligibility/return",
        headers=_headers(support_client, HARBOR),
    )
    refund = support_client.get(
        f"/orders/{HARBOR}/eligibility/refund",
        headers=_headers(support_client, HARBOR),
    )

    assert address.json() == {"eligible": True, "reason_code": "eligible"}
    assert delivered.json() == {"eligible": False, "reason_code": "already_delivered"}
    assert returns.json()["eligible"] is False
    assert returns.json()["reason_code"] == "not_delivered"
    assert "damaged" in returns.json()["allowed_reason_codes"]
    assert refund.status_code == 200
    assert refund.json()["eligible"] is True
    assert refund.json()["maximum_amount_cents"] == 4599
    assert refund.json()["currency"] == "USD"
    lowered = refund.text.lower()
    assert "payment" not in lowered
    assert "instrument" not in lowered
    assert "card" not in lowered


def test_each_seeded_aggregate_can_be_read(support_client: TestClient) -> None:
    tenant, order = _tenant_for(HARBOR)
    ticket_id = tenant["tickets"][0]["id"]
    customer_id = tenant["customers"][0]["id"]
    headers = _headers(support_client, HARBOR)

    customer = support_client.get(f"/customers/{customer_id}", headers=headers)
    shipment = support_client.get(f"/orders/{HARBOR}/shipment", headers=headers)
    ticket = support_client.get(f"/tickets/{ticket_id}", headers=headers)

    assert customer.status_code == 200
    assert customer.json()["email"] == tenant["customers"][0]["email"]
    assert customer.json()["display_name"] == "Ava Chen"
    assert shipment.status_code == 200
    assert shipment.json()["origin_hub"] == order["shipment"]["origin_hub"]
    assert shipment.json()["estimated_delivery_on"] == "2099-06-15"
    assert ticket.status_code == 200
    assert ticket.json()["summary"] == "Where is order ORD-10482?"
    assert "assigned_to" not in ticket.json()


def test_ticket_from_another_tenant_is_not_found(support_client: TestClient) -> None:
    tenant, _order = _tenant_for(HARBOR)
    ticket_id = tenant["tickets"][0]["id"]

    response = support_client.get(
        f"/tickets/{ticket_id}",
        headers=_headers(support_client, FIELDLINE),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "ticket_not_found"
    assert "ORD-10482" not in response.text


def test_missing_tenant_scope_is_rejected(support_client: TestClient) -> None:
    response = support_client.get(f"/orders/{HARBOR}")

    assert response.status_code == 401
    assert response.json() == {
        "code": "unauthorized",
        "message": "Sign in is required.",
    }


def test_order_pages_default_to_twenty_and_honor_the_cursor(
    support_client: TestClient, support_engine: Engine
) -> None:
    tenant, order = _tenant_for(HARBOR)
    address = ShippingAddress.model_validate(order["shipping_address"])
    with Session(support_engine) as session:
        repository = OrderRepository(session)
        for index in range(25):
            repository.insert(
                OrderRecord(
                    id=uuid4(),
                    tenant_id=UUID(str(tenant["id"])),
                    customer_id=UUID(str(order["customer_id"])),
                    order_number=f"ORD-3{index:04d}",
                    status=OrderStatus.FULFILLED,
                    currency="USD",
                    total_cents=100,
                    shipping_address=address,
                    created_at=datetime(2026, 9, 10, tzinfo=UTC) + timedelta(seconds=index),
                )
            )
        session.commit()

    headers = _headers(support_client, HARBOR)
    first = support_client.get("/orders", headers=headers)
    assert first.status_code == 200
    assert len(first.json()["items"]) == 20
    cursor = first.json()["next_cursor"]
    assert isinstance(cursor, str)

    second = support_client.get("/orders", headers=headers, params={"cursor": cursor})
    assert [item["order_number"] for item in second.json()["items"]]
    assert len(second.json()["items"]) == 6
    assert second.json()["next_cursor"] is None
    seen = [item["order_number"] for item in first.json()["items"] + second.json()["items"]]
    assert HARBOR in seen
    assert FIELDLINE not in seen
    assert len(seen) == len(set(seen))

    too_large = support_client.get("/orders", headers=headers, params={"limit": 101})
    assert too_large.status_code == 422
    assert too_large.json()["code"] == "invalid_request"
    invalid = support_client.get("/orders", headers=headers, params={"cursor": "not-a-cursor"})
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "invalid_cursor"


def test_seed_is_idempotent(support_client: TestClient, support_engine: Engine) -> None:
    seed_support_domain(support_engine)
    seed_support_domain(support_engine)

    listed = support_client.get("/orders", headers=_headers(support_client, HARBOR))
    assert [item["order_number"] for item in listed.json()["items"]] == [HARBOR]


def test_ticket_create_replays_the_same_key(support_client: TestClient) -> None:
    tenant, _order = _tenant_for(HARBOR)
    payload = {
        "customer_id": tenant["customers"][0]["id"],
        "priority": "high",
        "category": "order",
        "summary": "Need a copy of the invoice",
        "idempotency_key": "ticket-1",
    }
    headers = _headers(support_client, HARBOR)

    created = support_client.post("/tickets", headers=headers, json=payload)
    replayed = support_client.post("/tickets", headers=headers, json=payload)
    listed = support_client.get("/tickets", headers=headers)

    assert created.status_code == 201
    assert replayed.status_code == 200
    assert created.json() == replayed.json()
    assert created.json()["status"] == "open"
    assert sum(1 for item in listed.json()["items"] if item["id"] == created.json()["id"]) == 1

    conflict = support_client.post(
        "/tickets",
        headers=headers,
        json={**payload, "summary": "A different summary"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"


def test_openapi_documents_reads_and_omits_return_writes(support_client: TestClient) -> None:
    paths = support_client.get("/openapi.json").json()["paths"]

    assert "/orders/{order_number}" in paths
    assert "/orders/{order_number}/shipment" in paths
    assert "/orders/{order_number}/eligibility/refund" in paths
    assert "/customers/{customer_id}" in paths
    assert "/tickets" in paths
    assert "post" in paths["/tickets"]
    assert not any(path.startswith("/returns") or path.startswith("/refunds") for path in paths)


def test_repository_rejects_a_missing_tenant_scope(support_engine: Engine) -> None:
    with Session(support_engine) as session, pytest.raises(SupportError) as caught:
        OrderRepository(session).get(cast(UUID, None), HARBOR)

    assert caught.value.code == "tenant_required"


def test_support_services_do_not_reference_a_model_or_cloud_sdk() -> None:
    banned = ("boto3", "botocore", "openai", "anthropic", "fastapi")
    root = repo_root() / "services"
    for path in Path(root).rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for word in banned:
            assert word not in text, f"{path} mentions {word}"
    assert "boto3" not in sys.modules
