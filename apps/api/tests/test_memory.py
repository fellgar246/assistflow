"""Session memory, preference allowlists, and follow-up comparison."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from assistflow_contracts.agent import (
    AgentRunner,
    HistoryMessage,
    PromptRef,
    TurnContext,
)
from assistflow_contracts.conversation import MessageRole
from assistflow_contracts.memory import SessionFacts
from assistflow_conversations.commands import (
    ActorContext,
    append_customer_message,
    open_conversation,
)
from assistflow_customers.errors import SupportError
from assistflow_orders.repository import OrderRepository
from assistflow_test_fixtures.agent_scripts import follow_up_calls, reply_from_tools, select_script
from assistflow_test_fixtures.follow_ups import FOLLOW_UPS, score_follow_ups
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from assistflow_api.agents import InProcessAgentRunner
from assistflow_api.config import load_settings, repo_root
from assistflow_api.main import create_app
from assistflow_api.turns import complete_agent_turn
from assistflow_memory.allowlist import PREFERRED_LANGUAGE, PURPOSES
from assistflow_memory.factory import MemoryPorts, build_memory_ports
from assistflow_memory.hosted import AgentCorePreferenceMemory, AgentCoreSessionMemory
from assistflow_memory.limits import MemoryLimitError
from assistflow_memory.local_preferences import LocalPreferenceMemory
from assistflow_memory.local_session import ORDER_KIND, LocalSessionMemory
from assistflow_memory.models import MemoryPreferenceRow, SessionMemoryEventRow
from assistflow_runtime.limits import TurnLimits
from assistflow_runtime.loop import AgentLoop
from assistflow_runtime.mock_adapter import MockModelAdapter
from assistflow_runtime.prompts import PromptRegistry
from assistflow_tools import LocalToolGateway, build_registry, service_handlers
from assistflow_tools.writes import approved_write_handlers

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
FIELDLINE = UUID("22222222-2222-4222-8222-222222222222")
HARBOR_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001")
FIELDLINE_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0002")
ORDER = "ORD-10482"
OTHER_ORDER = "ORD-20817"
CARD = "4111111111111111"
TODAY = datetime(2026, 9, 30, tzinfo=UTC)


class _FakeHostedMemory:
    """In-process stand-in for the hosted memory client."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.records: dict[str, dict[str, Any]] = {}

    def create_event(self, **kwargs: Any) -> dict[str, Any]:
        self.events.append(kwargs)
        return {}

    def list_events(self, **kwargs: Any) -> dict[str, Any]:
        actor = kwargs["actorId"]
        session_id = kwargs["sessionId"]
        events = [
            {"eventTimestamp": item["eventTimestamp"], "payload": item["payload"]}
            for item in self.events
            if item["actorId"] == actor and item["sessionId"] == session_id
        ]
        return {"events": events}

    def batch_create_memory_records(self, **kwargs: Any) -> dict[str, Any]:
        records = kwargs["records"]
        assert isinstance(records, list)
        for record in records:
            assert isinstance(record, dict)
            record_id = record["memoryRecordId"]
            assert isinstance(record_id, str)
            self.records[record_id] = record
        return {}

    def list_memory_records(self, **kwargs: Any) -> dict[str, Any]:
        namespace = kwargs["namespace"]
        summaries = [
            {"memoryRecordId": record["memoryRecordId"], "content": record["content"]}
            for record in self.records.values()
            if record["namespace"] == namespace
        ]
        return {"memoryRecordSummaries": summaries}

    def delete_memory_record(self, **kwargs: Any) -> dict[str, Any]:
        record_id = kwargs["memoryRecordId"]
        assert isinstance(record_id, str)
        self.records.pop(record_id, None)
        return {}


def _explode(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("memory client constructed")


def _conversation(
    session: Session, tenant: UUID = HARBOR, customer: UUID = HARBOR_CUSTOMER
) -> UUID:
    opened = open_conversation(
        session,
        tenant,
        customer,
        f"memory-{uuid4()}",
        ActorContext("customer", customer, "corr-memory"),
    )
    return opened.conversation.id


def _loop(session: Session) -> AgentLoop:
    registry = build_registry(
        service_handlers(session, today=TODAY.date()),
        approved=approved_write_handlers(session, today=TODAY.date()),
    )
    return AgentLoop(
        MockModelAdapter(select_script, follow_up_calls),
        LocalToolGateway(registry, writes_enabled=True),
        PromptRegistry(repo_root() / "agent" / "prompts"),
        TurnLimits(8, 5, 4),
        reply_from_tools,
    )


def _turn(
    session: Session,
    message: str,
    *,
    conversation_id: UUID | None = None,
    history: list[str] | None = None,
    session_memory: SessionFacts | None = None,
    tenant: UUID = HARBOR,
    customer: UUID = HARBOR_CUSTOMER,
) -> Any:
    return _loop(session).run(
        TurnContext(
            tenant_id=tenant,
            customer_id=customer,
            conversation_id=conversation_id or uuid4(),
            correlation_id="corr-memory",
            customer_message=message,
            history=[
                HistoryMessage(role=MessageRole.CUSTOMER, content=item) for item in (history or [])
            ],
            prompt=PromptRef(id="local-support", version="1"),
            session_memory=session_memory,
        )
    )


def _order_ids(result: Any) -> list[str]:
    found: list[str] = []
    for call in result.proposed_tool_calls:
        order_id = call.arguments.get("order_id")
        if isinstance(order_id, str):
            found.append(order_id)
    return found


def _client(engine: Engine, **env: str) -> TestClient:
    app = create_app(load_settings(env), engine=engine)
    return TestClient(app)


def _headers(
    client: TestClient,
    tenant: UUID = HARBOR,
    customer: UUID = HARBOR_CUSTOMER,
    correlation: str = "corr-memory",
) -> dict[str, str]:
    from tokens import customer_headers

    return customer_headers(client, tenant, customer, correlation)


def _count(session: Session, model: type[SessionMemoryEventRow] | type[MemoryPreferenceRow]) -> int:
    counted = session.scalar(select(func.count()).select_from(model))
    return int(counted or 0)


def test_follow_up_with_session_memory_uses_the_remembered_order(support_engine: Engine) -> None:
    with Session(support_engine) as session:
        result = _turn(
            session,
            "change it to this address",
            history=[],
            session_memory=SessionFacts(last_order_id=ORDER, last_shipment_status="in_transit"),
        )
    assert ORDER in _order_ids(result)
    assert result.executed_tools[0].status == "pending_approval"


def test_follow_up_without_memory_uses_the_history_window(support_engine: Engine) -> None:
    with Session(support_engine) as session:
        result = _turn(
            session,
            "change it to this address",
            history=[f"Where is {ORDER}?"],
        )
    assert ORDER in _order_ids(result)


def test_ambiguous_follow_up_asks_when_history_and_memory_are_empty(
    support_engine: Engine,
) -> None:
    with Session(support_engine) as session:
        result = _turn(session, "change it to this address")
    assert _order_ids(result) == []
    assert "order number" in result.assistant_message.lower()
    assert result.proposed_tool_calls == []


def test_remembered_order_still_passes_the_tenant_check(support_engine: Engine) -> None:
    with Session(support_engine) as session:
        before = OrderRepository(session).require(HARBOR, ORDER).shipping_address.line1
        result = _turn(
            session,
            "change it to this address",
            session_memory=SessionFacts(last_order_id=OTHER_ORDER),
        )
        after = OrderRepository(session).require(HARBOR, ORDER).shipping_address.line1
    assert OTHER_ORDER in _order_ids(result)
    assert result.executed_tools[0].error_code == "not_found"
    assert result.executed_tools[0].status == "failed"
    assert after == before


def test_two_turns_record_the_order_and_reuse_it(support_engine: Engine) -> None:
    with _client(support_engine, SHORT_TERM_MEMORY_ENABLED="true") as client:
        opened = client.post(
            "/conversations",
            headers=_headers(client),
            json={"idempotency_key": "mem-open"},
        )
        assert opened.status_code == 201
        conversation_id = opened.json()["id"]
        first = client.post(
            f"/conversations/{conversation_id}/messages",
            headers=_headers(client),
            json={"content": f"Where is {ORDER}?", "idempotency_key": "mem-1"},
        )
        second = client.post(
            f"/conversations/{conversation_id}/messages",
            headers=_headers(client),
            json={"content": "change it to this address", "idempotency_key": "mem-2"},
        )
        transcript = client.get(
            f"/conversations/{conversation_id}/messages",
            headers=_headers(client),
        )
    assert first.status_code == 201
    assert second.status_code == 201
    approvals = [
        approval for item in transcript.json()["items"] for approval in item.get("approvals", [])
    ]
    assert approvals[0]["proposed_change"]["order_number"] == ORDER
    with Session(support_engine) as session:
        values = session.scalars(
            select(SessionMemoryEventRow.value).where(SessionMemoryEventRow.kind == ORDER_KIND)
        ).all()
    assert ORDER in values


def test_follow_up_accuracy_is_higher_with_session_memory() -> None:
    assert len(FOLLOW_UPS) >= 10
    enabled = score_follow_ups(memory_enabled=True)
    disabled = score_follow_ups(memory_enabled=False)
    assert enabled == 10
    assert disabled == 7
    assert enabled > disabled


def test_session_events_expire_and_stop_at_the_cap(support_engine: Engine) -> None:
    with Session(support_engine) as session:
        conversation_id = _conversation(session)
        port = LocalSessionMemory(session, max_events=2, max_session_minutes=20)
        port.record(HARBOR, HARBOR_CUSTOMER, conversation_id, ORDER_KIND, ORDER, TODAY)
        port.record(
            HARBOR,
            HARBOR_CUSTOMER,
            conversation_id,
            "last_shipment_status",
            "in_transit",
            TODAY,
        )
        row = session.scalar(select(SessionMemoryEventRow))
        assert row is not None
        assert row.expires_at - row.created_at == timedelta(minutes=20)
        try:
            port.record(
                HARBOR,
                HARBOR_CUSTOMER,
                conversation_id,
                ORDER_KIND,
                "ORD-10000",
                TODAY,
            )
            raise AssertionError("expected the event cap")
        except MemoryLimitError:
            pass
        assert _count(session, SessionMemoryEventRow) == 2
        expired = port.load(
            HARBOR,
            HARBOR_CUSTOMER,
            conversation_id,
            TODAY + timedelta(minutes=20),
        )
        assert expired.last_order_id is None
        try:
            port.load(FIELDLINE, HARBOR_CUSTOMER, conversation_id, TODAY)
            raise AssertionError("cross-tenant read was allowed")
        except SupportError as exc:
            assert exc.status_code == 404
        still = port.load(HARBOR, HARBOR_CUSTOMER, conversation_id, TODAY)
        assert still.last_order_id == ORDER


def test_session_write_does_not_store_a_secret(support_engine: Engine) -> None:
    with Session(support_engine) as session:
        conversation_id = _conversation(session)
        port = LocalSessionMemory(session, max_events=30, max_session_minutes=20)
        port.record(
            HARBOR,
            HARBOR_CUSTOMER,
            conversation_id,
            ORDER_KIND,
            f"Bearer abcdefghijklmnop {ORDER}",
            TODAY,
        )
        stored = " ".join(session.scalars(select(SessionMemoryEventRow.value)).all())
    assert "Bearer" not in stored
    assert CARD not in stored


def test_preference_stores_language_and_rejects_secrets(support_engine: Engine) -> None:
    with Session(support_engine) as session:
        port = LocalPreferenceMemory(session)
        stored = port.remember(HARBOR, HARBOR_CUSTOMER, PREFERRED_LANGUAGE, "English", TODAY)
        assert stored.value == "en"
        assert stored.purpose == PURPOSES[PREFERRED_LANGUAGE]
        assert stored.retention_deadline == TODAY + timedelta(days=365)
        row = session.scalar(select(MemoryPreferenceRow))
        assert row is not None
        assert row.tenant_id == HARBOR
        assert row.customer_id == HARBOR_CUSTOMER
        for key, value in (
            ("card_number", CARD),
            (PREFERRED_LANGUAGE, "password=hunter2"),
            (PREFERRED_LANGUAGE, CARD),
        ):
            try:
                port.remember(HARBOR, HARBOR_CUSTOMER, key, value, TODAY)
                raise AssertionError(f"stored {key}")
            except SupportError as exc:
                assert exc.code == "preference_rejected"
        assert _count(session, MemoryPreferenceRow) == 1
        assert session.scalar(select(MemoryPreferenceRow.value)) == "en"


def test_delete_removes_the_preference_for_that_customer_only(support_engine: Engine) -> None:
    with Session(support_engine) as session:
        port = LocalPreferenceMemory(session)
        port.remember(HARBOR, HARBOR_CUSTOMER, PREFERRED_LANGUAGE, "en", TODAY)
        try:
            port.delete(FIELDLINE, HARBOR_CUSTOMER)
            raise AssertionError("cross-tenant delete was allowed")
        except SupportError as exc:
            assert exc.status_code == 404
        try:
            port.load(FIELDLINE, HARBOR_CUSTOMER, TODAY)
            raise AssertionError("cross-tenant read was allowed")
        except SupportError as exc:
            assert exc.status_code == 404
        assert port.load(HARBOR, HARBOR_CUSTOMER, TODAY)[0].value == "en"
        port.delete(HARBOR, HARBOR_CUSTOMER)
        assert port.load(HARBOR, HARBOR_CUSTOMER, TODAY) == []


def test_preference_routes_are_tenant_scoped(support_engine: Engine) -> None:
    with Session(support_engine) as session:
        LocalPreferenceMemory(session).remember(
            HARBOR, HARBOR_CUSTOMER, PREFERRED_LANGUAGE, "es", TODAY
        )
        session.commit()
    with _client(support_engine, LONG_TERM_MEMORY_ENABLED="true") as client:
        denied = client.get(
            "/preferences",
            headers=_headers(client, tenant=FIELDLINE, customer=FIELDLINE_CUSTOMER),
        )
        listed = client.get("/preferences", headers=_headers(client))
        deleted = client.delete("/preferences", headers=_headers(client))
        empty = client.get("/preferences", headers=_headers(client))
    assert denied.status_code == 200
    assert denied.json()["items"] == []
    assert "es" not in denied.text
    assert listed.status_code == 200
    assert listed.json()["items"][0]["value"] == "es"
    assert listed.json()["items"][0]["purpose"] == PURPOSES[PREFERRED_LANGUAGE]
    assert deleted.status_code == 204
    assert empty.json()["items"] == []


def test_long_term_flag_off_does_not_construct_or_write(
    support_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(LocalPreferenceMemory, "__init__", _explode)
    monkeypatch.setattr(LocalSessionMemory, "__init__", _explode)
    monkeypatch.setattr("assistflow_memory.factory.build_hosted_memory_client", _explode)
    with _client(support_engine) as client:
        opened = client.post(
            "/conversations", headers=_headers(client), json={"idempotency_key": "off-open"}
        )
        posted = client.post(
            f"/conversations/{opened.json()['id']}/messages",
            headers=_headers(client),
            json={
                "content": "My preferred language is English",
                "idempotency_key": "off-msg",
            },
        )
    assert posted.status_code == 201
    with Session(support_engine) as session:
        assert _count(session, MemoryPreferenceRow) == 0
        assert _count(session, SessionMemoryEventRow) == 0


def test_address_change_still_works_with_both_memory_flags_off(
    support_client: TestClient, support_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(LocalPreferenceMemory, "__init__", _explode)
    monkeypatch.setattr(LocalSessionMemory, "__init__", _explode)
    monkeypatch.setattr("assistflow_memory.factory.build_hosted_memory_client", _explode)
    opened = support_client.post(
        "/conversations", headers=_headers(support_client), json={"idempotency_key": "addr-off"}
    )
    posted = support_client.post(
        f"/conversations/{opened.json()['id']}/messages",
        headers=_headers(support_client),
        json={
            "content": f"Please update the delivery address for {ORDER}",
            "idempotency_key": "addr-off-msg",
        },
    )
    transcript = support_client.get(
        f"/conversations/{opened.json()['id']}/messages",
        headers=_headers(support_client),
    )
    assert posted.status_code == 201
    approvals = [
        approval for item in transcript.json()["items"] for approval in item.get("approvals", [])
    ]
    assert approvals[0]["proposed_change"]["kind"] == "address"
    assert approvals[0]["status"] == "pending"
    with Session(support_engine) as session:
        assert _count(session, SessionMemoryEventRow) == 0
        assert _count(session, MemoryPreferenceRow) == 0


def test_a_turn_stores_a_stated_language(support_engine: Engine) -> None:
    with _client(support_engine, LONG_TERM_MEMORY_ENABLED="true") as client:
        opened = client.post(
            "/conversations", headers=_headers(client), json={"idempotency_key": "lang-open"}
        )
        posted = client.post(
            f"/conversations/{opened.json()['id']}/messages",
            headers=_headers(client),
            json={
                "content": "My preferred language is English",
                "idempotency_key": "lang-msg",
            },
        )
        listed = client.get("/preferences", headers=_headers(client))
    assert posted.status_code == 201
    item = listed.json()["items"][0]
    assert item["key"] == PREFERRED_LANGUAGE
    assert item["value"] == "en"
    assert item["purpose"] == PURPOSES[PREFERRED_LANGUAGE]
    assert item["retention_deadline"]


class _Capture:
    def __init__(self) -> None:
        self.context: TurnContext | None = None
        self._bound: AgentRunner | None = None
        self._runner = InProcessAgentRunner(
            load_settings({}),
            MockModelAdapter(select_script, follow_up_calls),
        )

    def bind(self, gateway: Any) -> "_Capture":
        self._bound = self._runner.bind(gateway)
        return self

    def run(self, context: TurnContext) -> Any:
        self.context = context
        assert self._bound is not None
        return self._bound.run(context)


def test_the_next_turn_does_not_receive_a_deleted_preference(support_engine: Engine) -> None:
    capture = _Capture()
    with Session(support_engine) as session:
        port = LocalPreferenceMemory(session)
        port.remember(HARBOR, HARBOR_CUSTOMER, PREFERRED_LANGUAGE, "en", TODAY)
        opened = open_conversation(
            session,
            HARBOR,
            HARBOR_CUSTOMER,
            "pref-next",
            ActorContext("customer", HARBOR_CUSTOMER, "corr-pref"),
        )
        written = append_customer_message(
            session,
            HARBOR,
            HARBOR_CUSTOMER,
            opened.conversation.id,
            f"Where is {ORDER}?",
            "pref-next-msg",
            ActorContext("customer", HARBOR_CUSTOMER, "corr-pref"),
            acknowledge=False,
        )
        port.delete(HARBOR, HARBOR_CUSTOMER)
        complete_agent_turn(
            session,
            HARBOR,
            HARBOR_CUSTOMER,
            opened.conversation.id,
            written.message.id,
            f"Where is {ORDER}?",
            "pref-next-msg",
            ActorContext("customer", HARBOR_CUSTOMER, "corr-pref"),
            capture,
            settings=load_settings({"LONG_TERM_MEMORY_ENABLED": "true"}),
            memory=MemoryPorts(preferences=port),
        )
    assert capture.context is not None
    assert capture.context.preferences == []


def test_disabled_flags_skip_the_hosted_client() -> None:
    ports = build_memory_ports(
        short_term_enabled=False,
        long_term_enabled=False,
        agentcore_enabled=True,
        max_events=30,
        max_session_minutes=20,
        memory_id="memory-1",
        hosted_client=_FakeHostedMemory(),
    )
    assert ports.session is None
    assert ports.preferences is None


def test_hosted_adapters_use_the_injected_client() -> None:
    client = _FakeHostedMemory()
    ports = build_memory_ports(
        short_term_enabled=True,
        long_term_enabled=True,
        agentcore_enabled=True,
        max_events=30,
        max_session_minutes=20,
        memory_id="memory-1",
        hosted_client=client,
    )
    assert isinstance(ports.session, AgentCoreSessionMemory)
    assert isinstance(ports.preferences, AgentCorePreferenceMemory)
    conversation_id = uuid4()
    assert ports.session is not None
    assert ports.preferences is not None
    ports.session.record(HARBOR, HARBOR_CUSTOMER, conversation_id, ORDER_KIND, ORDER, TODAY)
    loaded = ports.session.load(HARBOR, HARBOR_CUSTOMER, conversation_id, TODAY)
    hidden = ports.session.load(FIELDLINE, FIELDLINE_CUSTOMER, conversation_id, TODAY)
    stored = ports.preferences.remember(HARBOR, HARBOR_CUSTOMER, PREFERRED_LANGUAGE, "en", TODAY)
    ports.preferences.delete(FIELDLINE, FIELDLINE_CUSTOMER)
    assert loaded.last_order_id == ORDER
    assert hidden.last_order_id is None
    assert ports.preferences.load(HARBOR, HARBOR_CUSTOMER, TODAY) == [stored]
    ports.preferences.delete(HARBOR, HARBOR_CUSTOMER)
    assert ports.preferences.load(HARBOR, HARBOR_CUSTOMER, TODAY) == []


def test_hosted_client_is_built_only_when_agentcore_and_a_memory_flag_are_on(
    support_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def _built(region: str) -> _FakeHostedMemory:
        calls.append(region)
        return _FakeHostedMemory()

    monkeypatch.setattr("assistflow_memory.factory.build_hosted_memory_client", _built)
    with Session(support_engine) as session:
        local = build_memory_ports(
            short_term_enabled=True,
            long_term_enabled=False,
            agentcore_enabled=False,
            max_events=30,
            max_session_minutes=20,
            session=session,
            region="us-east-1",
        )
        assert calls == []
        assert isinstance(local.session, LocalSessionMemory)
        hosted = build_memory_ports(
            short_term_enabled=True,
            long_term_enabled=False,
            agentcore_enabled=True,
            max_events=30,
            max_session_minutes=20,
            session=session,
            region="us-east-1",
            memory_id="memory-1",
        )
    assert calls == ["us-east-1"]
    assert isinstance(hosted.session, AgentCoreSessionMemory)
