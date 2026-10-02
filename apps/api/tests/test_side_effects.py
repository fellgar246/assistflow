"""Side effects run after the response and stay idempotent when delivered twice."""

import json
import sys
import threading
import time
import types
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from assistflow_contracts.support import TicketCategory, TicketPriority
from assistflow_conversations.models import (
    AuditEventRow,
    ConversationRow,
    ConversationSummaryRow,
    EvaluationIntakeRow,
    EventOutboxRow,
    NotificationRow,
)
from assistflow_conversations.outbox import (
    APPROVAL_CONSUMED,
    CONVERSATION_ESCALATED,
    CONVERSATION_RESOLVED,
    TICKET_CREATED,
    DomainEvent,
    EventPublisher,
    entity_ids,
    event_from_body,
)
from assistflow_conversations.side_effects import (
    AUDIT_ACTION,
    apply_side_effects,
    should_sample,
)
from assistflow_tickets.commands import create_ticket
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from assistflow_api.config import load_settings
from assistflow_api.event_queue import InMemoryEventQueue
from assistflow_api.events import build_publisher
from assistflow_api.main import create_app

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
HARBOR_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001")
NORA = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbb0001")


def test_publish_does_not_run_the_handler_until_drain(support_engine: Engine) -> None:
    seen: list[UUID] = []
    event = _event(TICKET_CREATED, ticket_id=uuid4())

    def handle(item: DomainEvent) -> None:
        seen.append(item.event_id)
        with Session(support_engine) as session:
            apply_side_effects(session, item, sample_rate=0)

    queue = InMemoryEventQueue(handle)
    queue.publish(event)

    assert seen == []
    assert [item.event_id for item in queue.published()] == [event.event_id]
    assert queue.drain() == 1
    assert seen == [event.event_id]
    assert _count(support_engine, NotificationRow) == 1


def test_create_ticket_does_not_run_the_consumer_inside_the_transaction(
    support_engine: Engine,
) -> None:
    with Session(support_engine) as session:
        create_ticket(
            session,
            HARBOR,
            HARBOR_CUSTOMER,
            TicketPriority.NORMAL,
            TicketCategory.SHIPPING,
            "Package is late",
            "ticket-open",
            correlation_id="corr-ticket",
            actor_type="customer",
            actor_id=HARBOR_CUSTOMER,
        )
        assert _count_session(session, NotificationRow) == 0
        assert _count_session(session, EventOutboxRow) == 1
        session.rollback()

    assert _count(support_engine, EventOutboxRow) == 0


def test_replaying_a_ticket_does_not_enqueue_a_second_event(support_engine: Engine) -> None:
    with Session(support_engine) as session:
        create_ticket(
            session,
            HARBOR,
            HARBOR_CUSTOMER,
            TicketPriority.NORMAL,
            TicketCategory.SHIPPING,
            "Package is late",
            "ticket-replay",
            correlation_id="corr-replay",
            actor_type="customer",
            actor_id=HARBOR_CUSTOMER,
        )
        create_ticket(
            session,
            HARBOR,
            HARBOR_CUSTOMER,
            TicketPriority.NORMAL,
            TicketCategory.SHIPPING,
            "Package is late",
            "ticket-replay",
            correlation_id="corr-replay",
            actor_type="customer",
            actor_id=HARBOR_CUSTOMER,
        )
        names = session.scalars(select(EventOutboxRow.event_name)).all()
        session.commit()

    assert list(names) == [TICKET_CREATED]


def test_http_ticket_returns_while_the_consumer_is_blocked(
    support_client: TestClient, support_engine: Engine
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def blocked(_event: DomainEvent) -> None:
        entered.set()
        release.wait(timeout=5)

    _state(support_client).events.set_handler(blocked)
    try:
        started = time.perf_counter()
        response = support_client.post(
            "/tickets",
            headers=_customer(support_client),
            json=_ticket_body("slow-1"),
        )
        elapsed = time.perf_counter() - started

        assert response.status_code == 201
        assert elapsed < 1
        assert _state(support_client).events.published()
        assert _count(support_engine, NotificationRow) == 0
        assert entered.wait(2)
    finally:
        release.set()
        assert _state(support_client).events.wait_until_idle(2)


def test_a_failed_consumer_leaves_the_message_visible_for_retry(
    support_client: TestClient, support_engine: Engine
) -> None:
    def fail(_event: DomainEvent) -> None:
        raise RuntimeError("worker down")

    _state(support_client).events.set_handler(fail)
    response = support_client.post(
        "/tickets",
        headers=_customer(support_client),
        json=_ticket_body("fail-1"),
    )
    assert response.status_code == 201
    assert _state(support_client).events.wait_until_idle(2)

    retryable = _state(support_client).events.retryable()
    assert [item.name for item in retryable] == [TICKET_CREATED]
    with Session(support_engine) as session:
        ticket = session.get(EventOutboxRow, retryable[0].event_id)
        assert ticket is not None
        assert ticket.status == "published"


def test_publish_runs_after_commit_and_a_broker_error_keeps_the_ticket(
    support_client: TestClient, support_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    sequence: list[str] = []
    original = Session.commit
    _state(support_client).events.set_handler(lambda _event: None)

    def tracked(self: Session) -> None:
        sequence.append("commit")
        original(self)

    class Recording:
        def __init__(self, inner: EventPublisher) -> None:
            self._inner = inner

        def publish(self, event: DomainEvent) -> None:
            sequence.append("publish")
            self._inner.publish(event)

    publisher = cast(EventPublisher, _state(support_client).event_publisher)
    _state(support_client).event_publisher = Recording(publisher)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Session, "commit", tracked)
        created = support_client.post(
            "/tickets",
            headers=_customer(support_client),
            json=_ticket_body("order-1"),
        )

    assert created.status_code == 201
    assert sequence[0] == "commit"
    assert sequence.index("publish") > sequence.index("commit")

    class Broken:
        def publish(self, _event: DomainEvent) -> None:
            raise RuntimeError("broker down")

    _state(support_client).event_publisher = Broken()
    failed = support_client.post(
        "/tickets",
        headers=_customer(support_client),
        json=_ticket_body("order-2"),
    )
    assert failed.status_code == 201
    assert _state(support_client).events.wait_until_idle(2)
    with Session(support_engine) as session:
        pending = session.scalars(
            select(EventOutboxRow).where(EventOutboxRow.status == "pending")
        ).all()
    assert len(pending) == 1
    assert pending[0].attempts == 1
    captured = capsys.readouterr()
    assert "event_publish_failed" in captured.out + captured.err


def test_duplicate_delivery_does_not_repeat_notice_or_audit(support_engine: Engine) -> None:
    event = _event(CONVERSATION_RESOLVED, conversation_id=uuid4(), customer_id=HARBOR_CUSTOMER)
    _open_conversation(support_engine, UUID(event.entities["conversation_id"]))
    for _ in range(2):
        with Session(support_engine) as session:
            apply_side_effects(session, event, sample_rate=1)

    assert _count(support_engine, NotificationRow) == 1
    assert _count(support_engine, ConversationSummaryRow) == 1
    assert _count(support_engine, EvaluationIntakeRow) == 1
    with Session(support_engine) as session:
        recorded = session.scalar(
            select(func.count())
            .select_from(AuditEventRow)
            .where(AuditEventRow.action == AUDIT_ACTION)
        )
    assert int(recorded or 0) == 1


def test_unsampled_resolution_is_not_marked_and_sampling_is_stable() -> None:
    low = UUID(bytes=b"\x00\x00" + b"\x11" * 14)
    high = UUID(bytes=b"\xff\xff" + b"\x22" * 14)
    assert should_sample(low, 0.05) is True
    assert should_sample(high, 0.05) is False
    assert should_sample(high, 0) is False
    assert should_sample(high, 1) is True
    assert should_sample(high, 0.05) is should_sample(high, 0.05)


def test_event_body_keeps_ids_and_drops_secrets() -> None:
    ticket_id = uuid4()
    cleaned = entity_ids(
        {
            "ticket_id": ticket_id,
            "api_key": uuid4(),
            "password": uuid4(),
            "note": uuid4(),
            "conversation_id": None,
        }
    )
    assert cleaned == {"ticket_id": str(ticket_id)}
    event = _event(TICKET_CREATED, ticket_id=ticket_id)
    body = event.body()
    assert body["tenant_id"] == str(HARBOR)
    assert body["correlation_id"] == "corr-side-effect"
    assert body["event_id"] == str(event.event_id)
    assert "password" not in body
    assert "api_key" not in body
    restored = event_from_body({"detail-type": event.name, "detail": json.dumps(body)})
    assert restored.body() == body


def test_summary_failure_leaves_the_conversation_resolved(
    support_client: TestClient, support_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_session: Session, _tenant_id: UUID, _conversation_id: UUID) -> str:
        raise RuntimeError("summary failed")

    monkeypatch.setattr("assistflow_conversations.side_effects.summarize_conversation", fail)
    conversation_id = _resolve(support_client, support_engine)
    assert _state(support_client).events.wait_until_idle(2)

    with Session(support_engine) as session:
        row = session.get(ConversationRow, UUID(conversation_id))
        assert row is not None
        assert row.status == "resolved"
        summaries = session.scalar(select(func.count()).select_from(ConversationSummaryRow))
    assert int(summaries or 0) == 0
    retryable = {item.name for item in _state(support_client).events.retryable()}
    assert CONVERSATION_RESOLVED in retryable


def test_commands_publish_the_four_event_names(
    support_client: TestClient, support_engine: Engine, capsys: pytest.CaptureFixture[str]
) -> None:
    created = support_client.post(
        "/tickets",
        headers=_customer(support_client),
        json=_ticket_body("four-ticket"),
    )
    assert created.status_code == 201
    conversation_id = _resolve(support_client, support_engine)
    approval_conversation = _open(support_client)
    approval = _propose_address(support_client, approval_conversation)
    confirmed = support_client.post(
        f"/conversations/{approval_conversation}/approvals/{approval['id']}/confirm",
        headers=_customer(support_client, "confirm-side"),
        json={},
    )
    assert confirmed.status_code == 200
    assert _state(support_client).events.wait_until_idle(2)

    with Session(support_engine) as session:
        names = set(session.scalars(select(EventOutboxRow.event_name)).all())
        notices = session.scalars(
            select(NotificationRow).where(NotificationRow.tenant_id == HARBOR)
        ).all()
    assert names >= {
        TICKET_CREATED,
        CONVERSATION_ESCALATED,
        APPROVAL_CONSUMED,
        CONVERSATION_RESOLVED,
    }
    assert {item.event_name for item in notices} >= names
    assert conversation_id
    output = capsys.readouterr().out
    assert "notification_email_logged" in output


def test_local_mode_does_not_construct_an_aws_client(
    support_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    constructed: list[str] = []

    def client(name: str, region_name: str = "") -> object:
        constructed.append(name)
        return object()

    fake = types.ModuleType("boto3")
    fake.client = client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "boto3", fake)
    settings = load_settings(
        {
            "LOCAL_ONLY_MODE": "true",
            "AWS_ENABLED": "true",
            "ASYNC_WORKERS_ENABLED": "true",
            "EVENT_BUS_NAME": "assistflow-side-effects",
        }
    )
    app = create_app(settings, engine=support_engine)
    with TestClient(app) as client_http:
        response = client_http.post(
            "/tickets",
            headers=_customer(client_http),
            json=_ticket_body("local-1"),
        )
        assert response.status_code == 201
        assert _state(client_http).events.wait_until_idle(2)

    assert constructed == []
    assert "boto3" not in sys.modules or sys.modules["boto3"] is fake


def test_aws_publisher_is_built_only_when_workers_are_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[str] = []

    def client(name: str, region_name: str = "") -> object:
        constructed.append(name)
        return object()

    fake = types.ModuleType("boto3")
    fake.client = client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "boto3", fake)

    memory = InMemoryEventQueue(lambda _event: None)
    assert build_publisher(load_settings({}), memory) is memory
    assert constructed == []

    hosted = build_publisher(
        load_settings(
            {
                "AWS_ENABLED": "true",
                "ASYNC_WORKERS_ENABLED": "true",
                "EVENT_BUS_NAME": "assistflow-side-effects",
            }
        ),
        memory,
    )
    assert hosted is not memory
    assert constructed == ["events"]


def _state(client: TestClient) -> Any:
    return cast(Any, client).app.state


def test_hosted_worker_uses_the_same_handler(
    support_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    import assistflow_conversations.side_effects as effects

    import assistflow_api.side_effect_worker as worker

    assert worker.apply_side_effects is effects.apply_side_effects
    event = _event(TICKET_CREATED, ticket_id=uuid4())
    monkeypatch.setattr(
        "assistflow_api.side_effect_worker.create_db_engine", lambda _url: support_engine
    )
    monkeypatch.setattr(support_engine, "dispose", lambda: None)
    monkeypatch.setattr(
        "assistflow_api.side_effect_worker.load_settings",
        lambda: load_settings({"EVAL_SAMPLE_RATE": "0"}),
    )
    first = worker.lambda_handler({"Records": [{"body": json.dumps(event.body())}]}, None)
    second = worker.lambda_handler({"Records": [{"body": json.dumps(event.body())}]}, None)

    assert first == {"processed": 1}
    assert second == {"processed": 1}
    assert _count(support_engine, NotificationRow) == 1


def _event(name: str, **entities: UUID) -> DomainEvent:
    return DomainEvent(
        event_id=uuid4(),
        tenant_id=HARBOR,
        correlation_id="corr-side-effect",
        name=name,
        actor_type="customer",
        actor_id=HARBOR_CUSTOMER,
        entities=entity_ids(entities),
    )


def _open_conversation(engine: Engine, conversation_id: UUID) -> None:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    with Session(engine) as session:
        session.add(
            ConversationRow(
                id=conversation_id,
                tenant_id=HARBOR,
                customer_id=HARBOR_CUSTOMER,
                channel="web",
                status="resolved",
                agent_session_id=None,
                assigned_to=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def _count(engine: Engine, model: Any) -> int:
    with Session(engine) as session:
        return _count_session(session, model)


def _count_session(session: Session, model: Any) -> int:
    total = session.scalar(select(func.count()).select_from(model))
    return int(total or 0)


def _customer(client: TestClient, correlation: str = "corr-side") -> dict[str, str]:
    from tokens import customer_headers

    return customer_headers(client, HARBOR, HARBOR_CUSTOMER, correlation)


def _staff(client: TestClient) -> dict[str, str]:
    from tokens import staff_headers

    return staff_headers(client, HARBOR, NORA, "corr-staff-side")


def _ticket_body(key: str) -> dict[str, str]:
    return {
        "customer_id": str(HARBOR_CUSTOMER),
        "priority": "normal",
        "category": "shipping",
        "summary": "Package is late",
        "idempotency_key": key,
    }


def _open(client: TestClient) -> str:
    opened = client.post(
        "/conversations",
        headers=_customer(client),
        json={"idempotency_key": str(uuid4())},
    )
    assert opened.status_code == 201
    return str(opened.json()["id"])


def _resolve(client: TestClient, engine: Engine) -> str:
    from assistflow_tickets.commands import request_human_escalation

    conversation_id = _open(client)
    with Session(engine) as session:
        request_human_escalation(
            session,
            HARBOR,
            HARBOR_CUSTOMER,
            UUID(conversation_id),
            "Need a person",
            f"escalate-{conversation_id}",
            actor_type="customer",
            correlation_id="corr-escalate",
            actor_id=HARBOR_CUSTOMER,
        )
        session.commit()
    taken = client.post(
        f"/staff/conversations/{conversation_id}/takeover",
        headers=_staff(client),
        json={"idempotency_key": f"take-{conversation_id}"},
    )
    assert taken.status_code == 200
    resolved = client.post(
        f"/staff/conversations/{conversation_id}/resolve",
        headers=_staff(client),
        json={"idempotency_key": f"resolve-{conversation_id}"},
    )
    assert resolved.status_code == 200
    return conversation_id


def _propose_address(client: TestClient, conversation_id: str) -> dict[str, object]:
    posted = client.post(
        f"/conversations/{conversation_id}/messages",
        headers=_customer(client),
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
        headers=_customer(client),
    )
    for item in transcript.json()["items"]:
        approvals = item.get("approvals") or []
        if approvals:
            approval = approvals[0]
            assert isinstance(approval, dict)
            return approval
    raise AssertionError("expected an approval card")
