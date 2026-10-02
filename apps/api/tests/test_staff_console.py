"""Staff inbox, takeover, resolve, trace summary, and approval confirmation."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from assistflow_conversations.models import (
    AgentTraceRow,
    AgentTraceStepRow,
    ApprovalRequestRow,
    ToolExecutionRow,
)
from assistflow_tickets.commands import request_human_escalation
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from assistflow_api.config import load_settings
from assistflow_api.main import create_app

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
FIELDLINE = UUID("22222222-2222-4222-8222-222222222222")
HARBOR_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001")
NORA = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbb0001")
OWEN = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbb0002")
FULL_HASH = "abc12345" + ("f" * 56)


def test_inbox_is_tenant_scoped_and_empty_until_someone_is_waiting(
    support_client: TestClient, support_engine: Engine
) -> None:
    empty = support_client.get("/staff/inbox", headers=_staff())
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    assert empty.json()["counts"]["all"] == 0

    conversation_id, _ticket_id = _escalate(support_client, support_engine)
    harbor = support_client.get("/staff/inbox", headers=_staff())
    other = support_client.get("/staff/inbox", headers=_staff(FIELDLINE, OWEN))

    assert harbor.status_code == 200
    row = harbor.json()["items"][0]
    assert row["id"] == conversation_id
    assert row["customer_display_name"] == "Ava Chen"
    assert row["status"] == "escalated"
    assert row["updated_at"]
    assert other.status_code == 200
    assert other.json()["items"] == []


def test_takeover_reply_resolve_and_reopen(
    support_client: TestClient, support_engine: Engine
) -> None:
    conversation_id, ticket_id = _escalate(support_client, support_engine)
    taken = support_client.post(
        f"/staff/conversations/{conversation_id}/takeover",
        headers=_staff(),
        json={"idempotency_key": "take-1"},
    )
    again = support_client.post(
        f"/staff/conversations/{conversation_id}/takeover",
        headers=_staff(),
        json={"idempotency_key": "take-2"},
    )
    reply = support_client.post(
        f"/staff/conversations/{conversation_id}/messages",
        headers=_staff(),
        json={"content": "I can help with that order.", "idempotency_key": "reply-1"},
    )
    customer_view = support_client.get(
        f"/conversations/{conversation_id}/messages",
        headers=_customer(),
    )
    resolved = support_client.post(
        f"/staff/conversations/{conversation_id}/resolve",
        headers=_staff(),
        json={"idempotency_key": "resolve-1"},
    )
    resolved_again = support_client.post(
        f"/staff/conversations/{conversation_id}/resolve",
        headers=_staff(),
        json={"idempotency_key": "resolve-2"},
    )
    ticket = support_client.get(f"/staff/tickets/{ticket_id}", headers=_staff())
    reopened = support_client.post(
        f"/conversations/{conversation_id}/messages",
        headers=_customer(),
        json={"content": "One more question", "idempotency_key": "reopen-1"},
    )
    old_thread = support_client.get(
        f"/conversations/{conversation_id}/messages",
        headers=_customer(),
    )
    new_id = reopened.headers["x-conversation-id"]
    new_thread = support_client.get(
        f"/conversations/{new_id}/messages",
        headers=_customer(),
    )
    old_conversation = support_client.get(
        f"/conversations/{conversation_id}",
        headers=_customer(),
    )

    assert taken.status_code == 200
    assert taken.json()["assigned_to"] == str(NORA)
    assert again.json()["assigned_to"] == str(NORA)
    assert reply.status_code == 201
    assert reply.json()["role"] == "assistant"
    assert reply.json()["author_type"] == "support_agent"
    assert reply.json()["citations"] == []
    human = [
        item
        for item in customer_view.json()["items"]
        if item["content"] == "I can help with that order."
    ]
    assert human[0]["author_type"] == "support_agent"
    assert human[0]["role"] == "assistant"
    joined = [
        item["content"]
        for item in customer_view.json()["items"]
        if item["content"] == "Nora joined the conversation"
    ]
    assert joined == ["Nora joined the conversation"]
    assert resolved.json()["status"] == "resolved"
    assert resolved_again.json()["status"] == "resolved"
    assert ticket.json()["status"] == "resolved"
    assert ticket.json()["conversation_id"] == conversation_id
    assert ticket.json()["notes"] == [] or isinstance(ticket.json()["notes"], list)
    after = support_client.get(
        f"/staff/conversations/{conversation_id}/messages",
        headers=_staff(),
    )
    resolved_lines = [
        item["content"]
        for item in after.json()["items"]
        if item["content"] == "Conversation resolved"
    ]
    assert resolved_lines == ["Conversation resolved"]
    assert reopened.status_code == 201
    assert new_id != conversation_id
    assert old_conversation.json()["status"] == "resolved"
    assert "One more question" not in [item["content"] for item in old_thread.json()["items"]]
    assert "One more question" in [item["content"] for item in new_thread.json()["items"]]


def test_trace_summary_shows_a_denied_tool_without_a_payload(
    support_client: TestClient, support_engine: Engine
) -> None:
    conversation_id = _open(support_client)
    _insert_denied_trace(support_engine, conversation_id)
    summary = support_client.get(
        f"/staff/conversations/{conversation_id}/trace",
        headers=_staff(),
    )
    assert summary.status_code == 200
    body = summary.json()
    rendered = summary.text
    step = body["items"][0]["steps"][0]
    assert step["kind"] == "Tool call"
    assert step["tool_name"] == "get_order"
    assert step["status"] == "blocked"
    assert step["latency_ms"] == 320
    assert step["error_code"] == "tool_denied"
    assert "not available" in step["detail"]
    assert step["arguments_hash"] == FULL_HASH[:8]
    assert FULL_HASH not in rendered
    assert "PROVIDER_PAYLOAD" not in rendered
    for forbidden in ("prompt", "arguments", "body", "provider"):
        assert forbidden not in step


def test_staff_confirm_uses_the_same_approval_and_records_the_agent(
    support_client: TestClient, support_engine: Engine
) -> None:
    conversation_id = _open(support_client)
    approval = _propose_address(support_client, conversation_id)
    waiting = support_client.get(
        "/staff/inbox",
        headers=_staff(),
        params={"queue": "waiting_approval"},
    )
    assert waiting.json()["items"][0]["id"] == conversation_id
    assert waiting.json()["items"][0]["pending_approval_count"] >= 1

    confirmed = support_client.post(
        f"/staff/conversations/{conversation_id}/approvals/{approval['id']}/confirm",
        headers=_staff(correlation="confirm-staff"),
        json={},
    )
    again = support_client.post(
        f"/staff/conversations/{conversation_id}/approvals/{approval['id']}/confirm",
        headers=_staff(correlation="confirm-staff-2"),
        json={},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "consumed"
    assert confirmed.json()["approved_by"] == str(NORA)
    assert again.json()["approved_by"] == str(NORA)
    assert _line1(support_engine) == "42 Congress Avenue"


def test_staff_confirm_rejects_a_changed_arguments_hash(
    support_client: TestClient, support_engine: Engine
) -> None:
    conversation_id = _open(support_client)
    approval = _propose_address(support_client, conversation_id)
    before = _line1(support_engine)
    _tamper(support_engine, str(approval["id"]))
    denied = support_client.post(
        f"/staff/conversations/{conversation_id}/approvals/{approval['id']}/confirm",
        headers=_staff(),
        json={},
    )
    assert denied.status_code == 409
    assert denied.json()["code"] == "approval_hash_mismatch"
    assert _line1(support_engine) == before


def test_staff_routes_are_hidden_outside_local_mode(support_engine: Engine) -> None:
    remote = create_app(load_settings({"EXECUTION_MODE": "aws-demo"}), engine=support_engine)
    with TestClient(remote) as client:
        hidden = client.get("/dev/staff")
        inbox = client.get("/staff/inbox", headers=_staff())
    assert hidden.status_code == 404
    assert inbox.status_code == 404


def _open(client: TestClient) -> str:
    opened = client.post(
        "/conversations",
        headers=_customer(),
        json={"idempotency_key": str(uuid4())},
    )
    assert opened.status_code == 201
    return str(opened.json()["id"])


def _escalate(client: TestClient, engine: Engine) -> tuple[str, str]:
    conversation_id = _open(client)
    with Session(engine) as session:
        result = request_human_escalation(
            session,
            HARBOR,
            HARBOR_CUSTOMER,
            UUID(conversation_id),
            "Need a person to look at ORD-10482",
            f"escalate-{conversation_id}",
            actor_type="customer",
            correlation_id="corr-staff",
            actor_id=HARBOR_CUSTOMER,
        )
        session.commit()
        return conversation_id, str(result.ticket_id)


def _propose_address(client: TestClient, conversation_id: str) -> dict[str, object]:
    posted = client.post(
        f"/conversations/{conversation_id}/messages",
        headers=_customer(),
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
            "idempotency_key": f"address-{conversation_id}",
        },
    )
    assert posted.status_code == 201, posted.text
    transcript = client.get(
        f"/conversations/{conversation_id}/messages",
        headers=_customer(),
    )
    for item in transcript.json()["items"]:
        approvals = item.get("approvals") or []
        if approvals:
            approval = approvals[0]
            assert isinstance(approval, dict)
            return approval
    raise AssertionError("expected an approval card")


def _insert_denied_trace(engine: Engine, conversation_id: str) -> None:
    now = datetime.now(UTC)
    trace_id = uuid4()
    with Session(engine) as session:
        session.add(
            AgentTraceRow(
                id=trace_id,
                tenant_id=HARBOR,
                conversation_id=UUID(conversation_id),
                customer_id=HARBOR_CUSTOMER,
                correlation_id="corr-trace",
                prompt_id="support",
                prompt_version="1",
                stop_reason="completed",
                input_tokens=0,
                output_tokens=0,
                provider="mock",
                model_id="mock",
                created_at=now,
            )
        )
        session.add(
            AgentTraceStepRow(
                id=uuid4(),
                trace_id=trace_id,
                step_index=0,
                kind="tool_denial",
                latency_ms=320,
                input_summary="denied get_order",
            )
        )
        session.add(
            ToolExecutionRow(
                id=uuid4(),
                tenant_id=HARBOR,
                conversation_id=UUID(conversation_id),
                correlation_id="corr-trace",
                assistant_message_id=None,
                tool_name="get_order",
                arguments_hash=FULL_HASH,
                status="blocked",
                risk_level="tier3",
                approval_id=None,
                started_at=now,
                finished_at=now,
                result_summary="This action is not available.",
                error_code="tool_denied",
            )
        )
        session.commit()


def _tamper(engine: Engine, approval_id: str) -> None:
    with Session(engine) as session:
        row = session.get(ApprovalRequestRow, UUID(approval_id))
        assert row is not None
        row.arguments = {**dict(row.arguments), "line1": "9 Other Street"}
        session.commit()


def _line1(engine: Engine) -> str:
    from assistflow_orders.repository import OrderRepository

    with Session(engine) as session:
        return OrderRepository(session).require(HARBOR, "ORD-10482").shipping_address.line1


def _customer(correlation: str = "corr-staff") -> dict[str, str]:
    return {
        "X-Tenant-Id": str(HARBOR),
        "X-Customer-Id": str(HARBOR_CUSTOMER),
        "X-Correlation-Id": correlation,
    }


def _staff(
    tenant: UUID = HARBOR,
    agent: UUID = NORA,
    correlation: str = "corr-staff",
) -> dict[str, str]:
    return {
        "X-Tenant-Id": str(tenant),
        "X-Agent-Id": str(agent),
        "X-Correlation-Id": correlation,
    }
