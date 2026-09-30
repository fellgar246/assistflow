"""Bad credentials are rejected before a tool handler runs."""

from typing import Any
from uuid import UUID, uuid4

from assistflow_contracts.gateway import GatewayActor, sign_actor_context
from sqlalchemy.orm import Session

from assistflow_tools import build_registry, service_handlers
from assistflow_tools.local_gateway import LocalToolGateway
from assistflow_tools.registry import ToolRegistry
from assistflow_tools.targets import dispatch_tool_call

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
HARBOR_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001")
SECRET = "actor-context-secret"
TOKEN = "runtime-token"


class _SpyRegistry:
    def __init__(self, inner: ToolRegistry) -> None:
        self._inner = inner
        self.calls = 0

    def advertised(self) -> list[Any]:
        return self._inner.advertised()

    def lookup(self, name: str) -> Any:
        return self._inner.lookup(name)

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        return self._inner.execute(*args, **kwargs)


def _event(actor: GatewayActor | None, *, token: str = TOKEN) -> dict[str, Any]:
    signed = "" if actor is None else sign_actor_context(actor, SECRET)
    return {
        "authorization": f"Bearer {token}",
        "actor_context": signed,
        "name": "get_order",
        "arguments": {"order_id": "ORD-10482"},
    }


def test_bad_credential_is_rejected_before_the_handler(support_session: Session) -> None:
    registry = _SpyRegistry(build_registry(service_handlers(support_session)))
    actor = GatewayActor(
        tenant_id=HARBOR,
        customer_id=HARBOR_CUSTOMER,
        actor_type="customer",
        correlation_id="corr-target",
        conversation_id=uuid4(),
    )
    rejected = dispatch_tool_call(
        _event(actor, token="wrong"),
        registry,  # type: ignore[arg-type]
        expected_token=TOKEN,
        context_secret=SECRET,
    )

    assert rejected == {"ok": False, "error": "unauthorized"}
    assert registry.calls == 0


def test_signed_call_matches_the_local_gateway(support_session: Session) -> None:
    registry = build_registry(service_handlers(support_session))
    actor = GatewayActor(
        tenant_id=HARBOR,
        customer_id=HARBOR_CUSTOMER,
        actor_type="customer",
        correlation_id="corr-target",
        conversation_id=uuid4(),
    )
    dispatched = dispatch_tool_call(
        _event(actor),
        registry,
        expected_token=TOKEN,
        context_secret=SECRET,
    )
    direct = LocalToolGateway(registry).call_tool("get_order", {"order_id": "ORD-10482"}, actor)

    assert dispatched["ok"] is True
    assert dispatched["tool"]["body"] == direct.body


def test_tampered_actor_context_is_not_a_tenant(support_session: Session) -> None:
    registry = _SpyRegistry(build_registry(service_handlers(support_session)))
    event = _event(None)
    event["actor_context"] = '{"tenant_id":"11111111-1111-4111-8111-111111111111"}.deadbeef'
    dispatched = dispatch_tool_call(
        event,
        registry,  # type: ignore[arg-type]
        expected_token=TOKEN,
        context_secret=SECRET,
    )

    assert dispatched["ok"] is True
    assert dispatched["tool"]["error_code"] == "missing_actor"
    assert dispatched["tool"]["body"] is None
    assert registry.calls == 0
