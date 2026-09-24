"""Contract tests for the four read-only tools."""

import time
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from assistflow_tools import (
    ToolContext,
    ToolStatus,
    arguments_hash,
    build_registry,
    service_handlers,
)
from assistflow_tools.projections import contains_forbidden_key

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
FIELDLINE = UUID("22222222-2222-4222-8222-222222222222")
HARBOR_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001")
FIELDLINE_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0002")
HARBOR_TICKET = UUID("dddddddd-dddd-4ddd-8ddd-dddddddd0001")
ORDER = "ORD-10482"


def _context(tenant_id: UUID, customer_id: UUID, *, actor_type: str = "customer") -> ToolContext:
    return ToolContext(
        tenant_id=tenant_id,
        customer_id=customer_id,
        actor_type=actor_type,
        correlation_id="corr-tools",
        conversation_id=uuid4(),
    )


def test_argument_hash_is_stable_for_key_order() -> None:
    first = arguments_hash("get_order", {"order_id": "ORD-10482", "note": "a"})
    second = arguments_hash("get_order", {"note": "a", "order_id": "ORD-10482"})
    assert first == second
    assert first != arguments_hash("get_shipment", {"order_id": "ORD-10482", "note": "a"})


def test_get_order_returns_fixture_facts_and_hides_other_tenants(support_session: Session) -> None:
    registry = build_registry(service_handlers(support_session))
    found = registry.execute("get_order", {"order_id": ORDER}, _context(HARBOR, HARBOR_CUSTOMER))
    assert found.status is ToolStatus.SUCCEEDED
    assert found.body is not None
    assert found.body["shipping_city"] == "Austin"
    assert found.body["shipping_country"] == "US"
    assert found.body["shipment"]["origin_hub"] == "DFW"
    assert found.body["shipment"]["estimated_delivery_on"] == "2099-06-15"
    assert "line1" not in found.body
    assert contains_forbidden_key(found.body) is False

    hidden = registry.execute(
        "get_order", {"order_id": ORDER}, _context(FIELDLINE, FIELDLINE_CUSTOMER)
    )
    assert hidden.status is ToolStatus.FAILED
    assert hidden.error_code == "not_found"
    assert hidden.body is None
    assert "Austin" not in hidden.summary
    assert "DFW" not in hidden.summary


def test_get_shipment_returns_hub_and_delivery_date(support_session: Session) -> None:
    registry = build_registry(service_handlers(support_session))
    found = registry.execute("get_shipment", {"order_id": ORDER}, _context(HARBOR, HARBOR_CUSTOMER))
    assert found.status is ToolStatus.SUCCEEDED
    assert found.body is not None
    assert found.body["carrier_name"] == "Northline Parcel"
    assert found.body["origin_hub"] == "DFW"
    assert found.body["estimated_delivery_on"] == "2099-06-15"
    assert "password" not in found.body

    missing = registry.execute(
        "get_shipment", {"order_id": "ORD-00000"}, _context(HARBOR, HARBOR_CUSTOMER)
    )
    assert missing.status is ToolStatus.FAILED
    assert missing.body is None


def test_profile_and_ticket_omit_secret_keys(support_session: Session) -> None:
    registry = build_registry(service_handlers(support_session))
    profile = registry.execute(
        "get_customer_profile",
        {"customer_id": str(HARBOR_CUSTOMER)},
        _context(HARBOR, HARBOR_CUSTOMER),
    )
    ticket = registry.execute(
        "get_ticket",
        {"ticket_id": str(HARBOR_TICKET)},
        _context(HARBOR, HARBOR_CUSTOMER),
    )
    assert profile.status is ToolStatus.SUCCEEDED
    assert ticket.status is ToolStatus.SUCCEEDED
    assert profile.body is not None
    assert ticket.body is not None
    assert profile.body["display_name"] == "Ava Chen"
    assert ticket.body["summary"] == "Where is order ORD-10482?"
    assert contains_forbidden_key(profile.body) is False
    assert contains_forbidden_key(ticket.body) is False
    for marker in ("password", "token", "payment"):
        assert marker not in profile.body
        assert marker not in ticket.body


def test_customer_cannot_read_another_profile(support_session: Session) -> None:
    calls = {"count": 0}

    def profile(context: ToolContext, arguments: object) -> dict[str, object]:
        calls["count"] += 1
        return {"email": "hidden@example.com", "password": "nope"}

    registry = build_registry(
        {
            "get_customer_profile": profile,
            "get_order": profile,
            "get_shipment": profile,
            "get_ticket": profile,
        }
    )
    denied = registry.execute(
        "get_customer_profile",
        {"customer_id": str(FIELDLINE_CUSTOMER)},
        _context(HARBOR, HARBOR_CUSTOMER),
    )
    assert denied.status is ToolStatus.BLOCKED
    assert denied.body is None
    assert calls["count"] == 0
    assert "hidden@example.com" not in denied.summary


def test_invalid_arguments_do_not_call_the_handler() -> None:
    calls = {"count": 0}

    def handler(_context: ToolContext, _arguments: object) -> dict[str, object]:
        calls["count"] += 1
        return {"status": "should-not-run"}

    registry = build_registry(
        {
            name: handler
            for name in ("get_order", "get_shipment", "get_customer_profile", "get_ticket")
        }
    )
    context = _context(HARBOR, HARBOR_CUSTOMER)
    missing = registry.execute("get_order", {}, context)
    extra = registry.execute("get_order", {"order_id": ORDER, "tenant_id": str(HARBOR)}, context)
    unknown = registry.execute("issue_payment", {"order_id": ORDER}, context)
    assert missing.status is ToolStatus.FAILED
    assert missing.error_code == "validation_error"
    assert extra.status is ToolStatus.FAILED
    assert extra.error_code == "validation_error"
    assert unknown.status is ToolStatus.BLOCKED
    assert unknown.error_code == "tool_denied"
    assert calls["count"] == 0


def test_timeout_fails_without_a_stack_trace_and_retries_once() -> None:
    calls = {"count": 0}

    def sleeper(_context: ToolContext, _arguments: object) -> dict[str, object]:
        calls["count"] += 1
        time.sleep(0.2)
        return {"status": "late"}

    registry = build_registry(
        {
            name: sleeper
            for name in ("get_order", "get_shipment", "get_customer_profile", "get_ticket")
        },
        timeout_seconds=0.05,
    )
    outcome = registry.execute("get_order", {"order_id": ORDER}, _context(HARBOR, HARBOR_CUSTOMER))
    assert outcome.status is ToolStatus.FAILED
    assert outcome.error_code == "timeout"
    assert outcome.attempts == 2
    assert calls["count"] == 2
    assert outcome.body is None
    assert "Traceback" not in outcome.summary
    assert "Error" not in outcome.summary


def test_timeout_retries_only_once_then_can_succeed() -> None:
    calls = {"count": 0}

    def flaky(_context: ToolContext, _arguments: object) -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] == 1:
            time.sleep(0.2)
        return {"status": "fulfilled", "origin_hub": "DFW"}

    registry = build_registry({"get_order": flaky}, timeout_seconds=0.05)
    outcome = registry.execute("get_order", {"order_id": ORDER}, _context(HARBOR, HARBOR_CUSTOMER))
    assert outcome.status is ToolStatus.SUCCEEDED
    assert outcome.attempts == 2
    assert calls["count"] == 2
    assert outcome.body is not None
    assert outcome.body["origin_hub"] == "DFW"


def test_execution_cap_does_not_call_the_handler() -> None:
    calls = {"count": 0}

    def handler(_context: ToolContext, _arguments: object) -> dict[str, object]:
        calls["count"] += 1
        return {"status": "fulfilled"}

    registry = build_registry({"get_order": handler})
    blocked = registry.execute(
        "get_order",
        {"order_id": ORDER},
        _context(HARBOR, HARBOR_CUSTOMER),
        executions_used=5,
        max_executions=5,
    )
    assert blocked.status is ToolStatus.BLOCKED
    assert blocked.error_code == "tool_limit"
    assert calls["count"] == 0


def test_each_tool_rejects_a_missing_id_and_a_cross_tenant_read(support_session: Session) -> None:
    registry = build_registry(service_handlers(support_session))
    harbor = _context(HARBOR, HARBOR_CUSTOMER)
    other = _context(FIELDLINE, FIELDLINE_CUSTOMER)
    cases = (
        ("get_order", {"order_id": ORDER}, {}),
        ("get_shipment", {"order_id": ORDER}, {}),
        ("get_customer_profile", {"customer_id": str(HARBOR_CUSTOMER)}, {}),
        ("get_ticket", {"ticket_id": str(HARBOR_TICKET)}, {}),
    )
    for name, arguments, _empty in cases:
        found = registry.execute(name, arguments, harbor)
        hidden = registry.execute(name, arguments, other)
        invalid = registry.execute(name, {}, harbor)
        assert found.status is ToolStatus.SUCCEEDED
        assert hidden.body is None
        assert hidden.status in {ToolStatus.FAILED, ToolStatus.BLOCKED}
        assert invalid.status is ToolStatus.FAILED
        assert invalid.error_code == "validation_error"
        assert "Traceback" not in (hidden.summary + invalid.summary)
