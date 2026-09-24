"""Store a conversation, replay it, and attach a ticket under one correlation id."""

from uuid import UUID

from assistflow_contracts.conversation import ConversationStatus, MessageRole
from assistflow_conversations.audit import audit_payload
from assistflow_conversations.commands import (
    ActorContext,
    append_message,
    change_conversation_status,
    open_conversation,
)
from assistflow_conversations.repository import AuditRepository
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from assistflow_api.replay import replay_conversation

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
FIELDLINE = UUID("22222222-2222-4222-8222-222222222222")
HARBOR_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001")
CORRELATION = "corr-conversation-1"


def _customer_actor(correlation: str) -> ActorContext:
    return ActorContext(
        actor_type="customer",
        actor_id=HARBOR_CUSTOMER,
        correlation_id=correlation,
    )


def _headers(tenant_id: UUID, customer_id: UUID | None = None) -> dict[str, str]:
    headers = {"X-Tenant-Id": str(tenant_id), "X-Correlation-Id": CORRELATION}
    if customer_id is not None:
        headers["X-Customer-Id"] = str(customer_id)
    return headers


def test_audit_payload_drops_tokens_and_marks_truncation() -> None:
    payload = audit_payload(
        {
            "conversation_id": "abc",
            "access_token": "secret-token",
            "note": "n" * 300,
        }
    )

    assert "access_token" not in payload
    assert "token" not in payload
    assert payload["truncated"] is True
    assert payload["note"] == "n" * 256
    assert payload["conversation_id"] == "abc"


def test_conversation_is_stored_and_replayed_in_order(
    support_client: TestClient, support_engine: Engine
) -> None:
    headers = _headers(HARBOR, HARBOR_CUSTOMER)
    created = support_client.post(
        "/conversations",
        headers=headers,
        json={"idempotency_key": "conv-1"},
    )
    assert created.status_code == 201
    assert created.json()["status"] == "open"
    assert created.json()["channel"] == "web"
    assert created.headers["X-Correlation-Id"] == CORRELATION
    conversation_id = created.json()["id"]

    rejected = support_client.post(
        "/conversations",
        headers=headers,
        json={"idempotency_key": "conv-2", "tenant_id": str(FIELDLINE)},
    )
    assert rejected.status_code == 422

    customer = support_client.post(
        f"/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": "Where is my order?", "idempotency_key": "msg-1"},
    )
    assert customer.status_code == 201
    assert customer.json()["role"] == "customer"
    assert customer.json()["content"] == "Where is my order?"

    with Session(support_engine) as session:
        append_message(
            session,
            HARBOR,
            HARBOR_CUSTOMER,
            UUID(conversation_id),
            MessageRole.ASSISTANT,
            "It is in transit from DFW.",
            "msg-assistant-1",
            ActorContext(actor_type="system", actor_id=HARBOR_CUSTOMER, correlation_id=CORRELATION),
        )
        session.commit()

    first = support_client.get(f"/conversations/{conversation_id}/messages", headers=headers)
    second = support_client.get(f"/conversations/{conversation_id}/messages", headers=headers)
    assert first.status_code == 200
    assert first.json() == second.json()
    assert [item["role"] for item in first.json()["items"]] == ["customer", "assistant"]
    assert [item["content"] for item in first.json()["items"]] == [
        "Where is my order?",
        "It is in transit from DFW.",
    ]

    listed = support_client.get("/conversations", headers=headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [conversation_id]

    hidden = support_client.get(
        f"/conversations/{conversation_id}/messages",
        headers=_headers(FIELDLINE, HARBOR_CUSTOMER),
    )
    assert hidden.status_code == 404
    assert hidden.json()["code"] == "conversation_not_found"


def test_ticket_links_to_the_conversation_inside_the_tenant(
    support_client: TestClient, support_engine: Engine
) -> None:
    headers = _headers(HARBOR, HARBOR_CUSTOMER)
    created = support_client.post(
        "/conversations",
        headers=headers,
        json={"idempotency_key": "conv-ticket"},
    )
    conversation_id = created.json()["id"]
    ticket = support_client.post(
        "/tickets",
        headers={"X-Tenant-Id": str(HARBOR), "X-Correlation-Id": CORRELATION},
        json={
            "customer_id": str(HARBOR_CUSTOMER),
            "priority": "normal",
            "category": "order",
            "summary": "Order status",
            "idempotency_key": "ticket-conv-1",
            "conversation_id": conversation_id,
        },
    )
    assert ticket.status_code == 201
    assert ticket.json()["conversation_id"] == conversation_id

    listed = support_client.get("/tickets", headers={"X-Tenant-Id": str(HARBOR)})
    assert any(item["id"] == ticket.json()["id"] for item in listed.json()["items"])

    opened = support_client.get(
        f"/tickets/{ticket.json()['id']}",
        headers={"X-Tenant-Id": str(HARBOR)},
    )
    assert opened.status_code == 200
    other = support_client.get(
        f"/tickets/{ticket.json()['id']}",
        headers={"X-Tenant-Id": str(FIELDLINE)},
    )
    assert other.status_code == 404
    assert other.json()["code"] == "ticket_not_found"

    with Session(support_engine) as session:
        replay = replay_conversation(session, HARBOR, UUID(conversation_id))
        events = AuditRepository(session).list_for_correlation(HARBOR, CORRELATION)
        session.rollback()

    assert replay.conversation.status is ConversationStatus.OPEN
    assert replay.ticket_ids == [UUID(ticket.json()["id"])]
    actions = [event.action for event in events]
    assert "conversation.created" in actions
    assert "ticket.created" in actions
    assert all(event.correlation_id == CORRELATION for event in events)
    assert all("token" not in event.payload for event in events)


def test_status_change_and_audit_share_one_transaction(support_engine: Engine) -> None:
    with Session(support_engine) as session:
        opened = open_conversation(
            session,
            HARBOR,
            HARBOR_CUSTOMER,
            "conv-status",
            _customer_actor("corr-status"),
        )
        change_conversation_status(
            session,
            HARBOR,
            opened.conversation.id,
            ConversationStatus.ESCALATED,
            _customer_actor("corr-status"),
        )
        events = AuditRepository(session).list_for_correlation(HARBOR, "corr-status")
        session.rollback()

    assert [event.action for event in events] == [
        "conversation.created",
        "conversation.status_changed",
    ]

    with Session(support_engine) as session:
        remaining = AuditRepository(session).list_for_correlation(HARBOR, "corr-status")
    assert remaining == []
