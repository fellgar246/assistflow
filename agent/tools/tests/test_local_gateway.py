"""Contract tests for the local tool gateway."""

from uuid import UUID, uuid4

from assistflow_contracts.gateway import READ_TOOL_NAMES, TIER3_TOOL_NAMES, GatewayActor
from sqlalchemy.orm import Session

from assistflow_tools import ToolContext, build_registry, service_handlers
from assistflow_tools.local_gateway import LocalToolGateway

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
HARBOR_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001")
ORDER = "ORD-10482"


def _actor() -> GatewayActor:
    return GatewayActor(
        tenant_id=HARBOR,
        customer_id=HARBOR_CUSTOMER,
        actor_type="customer",
        correlation_id="corr-gateway",
        conversation_id=uuid4(),
    )


def _tool_context(actor: GatewayActor) -> ToolContext:
    return ToolContext(
        tenant_id=actor.tenant_id,
        customer_id=actor.customer_id,
        actor_type=actor.actor_type,
        correlation_id=actor.correlation_id,
        conversation_id=actor.conversation_id,
    )


def test_list_includes_tier0_reads_and_omits_tier3(support_session: Session) -> None:
    gateway = LocalToolGateway(build_registry(service_handlers(support_session)))
    names = {tool.name for tool in gateway.list_tools()}

    assert {"get_order", "get_shipment", "get_customer_profile", "get_ticket"} <= names
    assert "search_support_policy" in names
    assert names <= READ_TOOL_NAMES
    assert names.isdisjoint(TIER3_TOOL_NAMES)
    assert "create_refund_request" not in names
    assert "issue_payment" not in names


def test_get_order_matches_the_registry_projection(support_session: Session) -> None:
    registry = build_registry(service_handlers(support_session))
    gateway = LocalToolGateway(registry)
    actor = _actor()
    direct = registry.execute("get_order", {"order_id": ORDER}, _tool_context(actor))
    via = gateway.call_tool("get_order", {"order_id": ORDER}, actor)

    assert via.status == "succeeded"
    assert via.body == direct.body
    assert via.body is not None
    assert via.body["shipment"]["origin_hub"] == "DFW"


def test_unknown_tool_is_rejected(support_session: Session) -> None:
    gateway = LocalToolGateway(build_registry(service_handlers(support_session)))
    outcome = gateway.call_tool("issue_payment", {"order_id": ORDER}, _actor())

    assert outcome.status == "blocked"
    assert outcome.error_code == "tool_denied"
    assert outcome.body is None


def test_invalid_schema_does_not_return_a_body(support_session: Session) -> None:
    gateway = LocalToolGateway(build_registry(service_handlers(support_session)))
    outcome = gateway.call_tool("get_order", {}, _actor())

    assert outcome.status == "failed"
    assert outcome.error_code == "validation_error"
    assert outcome.body is None


def test_missing_actor_is_rejected(support_session: Session) -> None:
    gateway = LocalToolGateway(build_registry(service_handlers(support_session)))
    outcome = gateway.call_tool("get_order", {"order_id": ORDER}, None)

    assert outcome.status == "blocked"
    assert outcome.error_code == "missing_actor"
    assert outcome.body is None


def test_tier2_call_is_blocked_without_approval(support_session: Session) -> None:
    gateway = LocalToolGateway(build_registry(service_handlers(support_session)))
    outcome = gateway.call_tool(
        "create_refund_request",
        {"order_id": ORDER, "amount_cents": 100},
        _actor(),
    )

    assert outcome.status == "blocked"
    assert outcome.error_code == "tool_denied"
    assert outcome.body is None


def test_sql_shell_and_url_arguments_are_refused(support_session: Session) -> None:
    gateway = LocalToolGateway(build_registry(service_handlers(support_session)))
    actor = _actor()
    cases = [
        {"order_id": ORDER, "sql": "select * from orders"},
        {"order_id": "select * from orders"},
        {"order_id": "https://example.test/hook"},
        {"order_id": "curl https://example.test"},
    ]
    for arguments in cases:
        outcome = gateway.call_tool("get_order", arguments, actor)
        assert outcome.status == "blocked"
        assert outcome.error_code == "invalid_arguments"
        assert outcome.body is None
