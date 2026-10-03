"""Hosted gateway client, import boundary, and operator policy checks."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from assistflow_contracts.agent import (
    ExecutedTool,
    PromptRef,
    ToolSchema,
    TurnContext,
)
from assistflow_contracts.gateway import (
    READ_TOOL_NAMES,
    GatewayActor,
    verify_actor_context,
)
from assistflow_test_fixtures.agent_scripts import follow_up_calls, reply_from_tools, select_script
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from assistflow_api.config import load_settings, repo_root
from assistflow_api.runtime_entry import run_payload
from assistflow_runtime.gateway import (
    AgentCoreToolGateway,
    GatewayDeniedError,
    GatewayTransportError,
    UnavailableGatewayTransport,
    build_agentcore_gateway,
)
from assistflow_runtime.limits import TurnLimits
from assistflow_runtime.loop import AgentLoop
from assistflow_runtime.mock_adapter import MockModelAdapter
from assistflow_runtime.prompts import PromptRegistry
from assistflow_tools import LocalToolGateway, build_registry, service_handlers
from assistflow_tools.targets import dispatch_tool_call

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
HARBOR_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001")
SECRET = "actor-context-secret"
TOKEN = "runtime-token"
_COMMERCE = (
    "assistflow_orders",
    "assistflow_shipping",
    "assistflow_returns",
    "assistflow_refunds",
    "assistflow_tickets",
    "assistflow_customers",
    "services.orders",
    "services.shipping",
    "services.returns",
    "services.refunds",
    "services.tickets",
    "services.customers",
)


class ScriptedTransport:
    def __init__(
        self,
        document: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.document = document if document is not None else {"result": {"tools": []}}
        self.error = error
        self.calls: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    def request(
        self,
        method: str,
        params: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        self.calls.append((method, params, headers))
        if self.error is not None:
            raise self.error
        return self.document


def _actor() -> GatewayActor:
    return GatewayActor(
        tenant_id=HARBOR,
        customer_id=HARBOR_CUSTOMER,
        actor_type="customer",
        correlation_id="corr-hosted-gateway",
        conversation_id=uuid4(),
    )


def _client(transport: ScriptedTransport, *, secret: str = SECRET) -> AgentCoreToolGateway:
    return AgentCoreToolGateway(transport, inbound_token=TOKEN, context_secret=secret)


def test_hosted_list_omits_tier3_names() -> None:
    transport = ScriptedTransport(
        {
            "result": {
                "tools": [
                    {"name": "get_order", "description": "Read one order.", "inputSchema": {}},
                    {"name": "issue_payment", "description": "Forbidden.", "inputSchema": {}},
                    {"name": "create_refund_request", "description": "Write.", "inputSchema": {}},
                ]
            }
        }
    )
    names = {tool.name for tool in _client(transport).list_tools()}

    assert names == {"get_order"}
    assert names <= READ_TOOL_NAMES


def test_hosted_call_returns_the_tool_body() -> None:
    body = {"order_id": "ORD-10482", "status": "paid"}
    tool = ExecutedTool(
        name="get_order",
        status="succeeded",
        summary="get_order succeeded",
        body=body,
        risk_level="tier0",
        arguments_hash="ab" * 32,
    )
    transport = ScriptedTransport({"result": tool.model_dump(mode="json")})
    outcome = _client(transport).call_tool("get_order", {"order_id": "ORD-10482"}, _actor())

    assert outcome.status == "succeeded"
    assert outcome.body == body
    assert transport.calls[0][0] == "tools/call"
    assert "tenant_id" not in transport.calls[0][1]["arguments"]
    assert transport.calls[0][2]["authorization"] == f"Bearer {TOKEN}"
    parsed = verify_actor_context(transport.calls[0][2]["x-actor-context"], SECRET)
    assert parsed is not None
    assert parsed.tenant_id == HARBOR


def test_hosted_unknown_invalid_and_missing_actor_skip_the_network() -> None:
    transport = ScriptedTransport()
    client = _client(transport)
    unknown = client.call_tool("issue_payment", {}, _actor())
    unsafe = client.call_tool("get_order", {"sql": "select * from orders"}, _actor())
    missing = client.call_tool("get_order", {"order_id": "ORD-10482"}, None)

    assert unknown.error_code == "tool_denied"
    assert unsafe.error_code == "invalid_arguments"
    assert missing.error_code == "missing_actor"
    assert unknown.body is None
    assert unsafe.body is None
    assert missing.body is None
    assert transport.calls == []


def test_gateway_failure_is_a_tool_result() -> None:
    transport = ScriptedTransport(error=GatewayTransportError("down"))
    outcome = _client(transport).call_tool("get_order", {"order_id": "ORD-10482"}, _actor())

    assert outcome.status == "failed"
    assert outcome.error_code == "gateway_unavailable"
    assert outcome.body is None


def test_denied_gateway_response_is_a_blocked_tool() -> None:
    transport = ScriptedTransport(error=GatewayDeniedError())
    outcome = _client(transport).call_tool("get_order", {"order_id": "ORD-10482"}, _actor())

    assert outcome.status == "blocked"
    assert outcome.error_code == "denied"
    assert outcome.body is None


def test_empty_gateway_url_does_not_open_a_connection() -> None:
    gateway = build_agentcore_gateway(url="", token=TOKEN, secret=SECRET)
    assert isinstance(gateway._transport, UnavailableGatewayTransport)
    outcome = gateway.call_tool("get_order", {"order_id": "ORD-10482"}, _actor())
    assert outcome.status == "failed"
    assert outcome.body is None


def test_signed_round_trip_matches_the_local_projection(support_engine: Engine) -> None:
    actor = _actor()
    with Session(support_engine) as session:
        registry = build_registry(service_handlers(session))
        direct = LocalToolGateway(registry).call_tool("get_order", {"order_id": "ORD-10482"}, actor)

        class Boundary:
            def request(
                self,
                method: str,
                params: dict[str, Any],
                headers: dict[str, str],
            ) -> dict[str, Any]:
                del method
                event = {
                    "authorization": headers.get("authorization", ""),
                    "actor_context": headers.get("x-actor-context", ""),
                    "name": params.get("name"),
                    "arguments": params.get("arguments"),
                }
                body = dispatch_tool_call(
                    event,
                    registry,
                    expected_token=TOKEN,
                    context_secret=SECRET,
                )
                if body.get("error") == "unauthorized":
                    raise GatewayDeniedError()
                tool = body["tool"]
                if not isinstance(tool, dict):
                    raise GatewayTransportError("The gateway response was not a tool result.")
                return {"result": tool}

        hosted = AgentCoreToolGateway(
            Boundary(),
            inbound_token=TOKEN,
            context_secret=SECRET,
        ).call_tool("get_order", {"order_id": "ORD-10482"}, actor)
        session.rollback()

    assert hosted.body == direct.body
    assert hosted.body is not None
    assert hosted.body["shipment"]["origin_hub"] == "DFW"


def test_denied_lookup_does_not_invent_the_order() -> None:
    class Denied:
        def list_tools(self) -> list[ToolSchema]:
            return [
                ToolSchema(
                    name="get_order",
                    description="Read one order.",
                    input_schema={"type": "object"},
                )
            ]

        def call_tool(
            self,
            name: str,
            arguments: dict[str, Any],
            actor_context: GatewayActor | None,
        ) -> ExecutedTool:
            del arguments, actor_context
            return ExecutedTool(
                name=name,
                status="blocked",
                error_code="denied",
                summary="The gateway denied that lookup.",
                body=None,
                risk_level="tier0",
                arguments_hash="ab" * 32,
            )

    result = AgentLoop(
        MockModelAdapter(select_script, follow_up_calls),
        Denied(),
        PromptRegistry(repo_root() / "agent" / "prompts"),
        TurnLimits(8, 5, 4),
        reply_from_tools,
    ).run(
        TurnContext(
            tenant_id=HARBOR,
            customer_id=HARBOR_CUSTOMER,
            conversation_id=uuid4(),
            correlation_id="corr-denied",
            customer_message="Where is ORD-10482?",
            history=[],
            prompt=PromptRef(id="local-support", version="1"),
        )
    )

    assert result.assistant_message == (
        "I cannot complete that lookup. Please narrow the request, or wait for a person."
    )
    assert "DFW" not in result.assistant_message
    assert "2099-06-15" not in result.assistant_message
    assert "Austin" not in result.assistant_message


def test_runtime_package_does_not_import_commerce_services() -> None:
    root = repo_root() / "agent" / "runtime" / "src"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith(("import ", "from ")):
                continue
            for name in _COMMERCE:
                if name in stripped:
                    offenders.append(f"{path.name}:{name}")
    assert offenders == []


def test_local_handler_does_not_construct_the_hosted_gateway(
    support_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbid(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("hosted gateway constructed")

    monkeypatch.setattr("assistflow_runtime.gateway.build_agentcore_gateway", forbid)
    settings = load_settings({})
    turn = _turn("Where is ORD-10482?")
    with Session(support_engine) as session:
        body = run_payload(session, settings, {"turn": turn.model_dump(mode="json")})
        session.rollback()

    message = body["result"]["assistant_message"]
    assert "DFW" in message
    assert "2099-06-15" in message


def test_enabled_handler_skips_commerce_handlers(
    support_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbid(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("commerce handlers")

    def forbid_network(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("gateway network")

    monkeypatch.setattr("assistflow_tools.handlers.service_handlers", forbid)
    monkeypatch.setattr("assistflow_runtime.gateway.UrllibGatewayTransport", forbid_network)
    settings = load_settings({"AGENTCORE_ENABLED": "true"})
    turn = _turn("Where is ORD-10482?")
    with Session(support_engine) as session:
        body = run_payload(session, settings, {"turn": turn.model_dump(mode="json")})
        session.rollback()

    message = body["result"]["assistant_message"]
    assert "DFW" not in message
    assert "2099-06-15" not in message
    assert "Austin" not in message


def test_gateway_policy_is_limited_to_tool_resources() -> None:
    module = repo_root() / "infra" / "modules" / "agentcore_gateway"
    tool_arn = "arn:aws:lambda:us-east-1:123456789012:function:assistflow-read-tools"
    gateway_arn = "arn:aws:bedrock-agentcore:us-east-1:123456789012:gateway/assistflow-tools"
    log_group_arn = (
        "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/assistflow-read-tools:*"
    )
    rendered = {
        "invoke": _render(module / "gateway_invoke.json.tftpl", {"tool_function_arn": tool_arn}),
        "runtime": _render(module / "runtime_invoke.json.tftpl", {"gateway_arn": gateway_arn}),
        "logs": _render(module / "lambda_logs.json.tftpl", {"log_group_arn": log_group_arn}),
    }
    invoke = rendered["invoke"]["Statement"][0]
    assert invoke["Action"] == ["lambda:InvokeFunction"]
    assert invoke["Resource"] == tool_arn
    assert rendered["runtime"]["Statement"][0]["Resource"].endswith("gateway/assistflow-tools")
    for policy in rendered.values():
        assert _wildcard_on_all_resources(policy) is False
    source = (module / "main.tf").read_text(encoding="utf-8")
    dev = (repo_root() / "infra" / "environments" / "dev" / "main.tf").read_text(encoding="utf-8")
    gateway_block = dev.split('module "agentcore_gateway"', maxsplit=1)[1]
    gateway_block = gateway_block.split("\n}", maxsplit=1)[0]
    assert "count = var.enabled ? 1 : 0" in source
    assert "var.enable_agentcore" in gateway_block
    assert 'Resource = "*"' not in source
    assert 'Action = "*"' not in source


def test_gateway_smoke_skips_without_credentials() -> None:
    script = repo_root() / "scripts" / "smoke_gateway.py"
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "AGENTCORE_GATEWAY_URL",
            "AGENTCORE_GATEWAY_TOKEN",
            "AGENTCORE_ACTOR_CONTEXT_SECRET",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_PROFILE",
            "AWS_SESSION_TOKEN",
        }
    }
    completed = subprocess.run(
        [sys.executable, str(script)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    assert "skipped" in completed.stdout


def _turn(message: str) -> TurnContext:
    return TurnContext(
        tenant_id=HARBOR,
        customer_id=HARBOR_CUSTOMER,
        conversation_id=uuid4(),
        correlation_id="corr-gateway-entry",
        customer_message=message,
        history=[],
        prompt=PromptRef(id="local-support", version="1"),
    )


def _render(path: Path, values: dict[str, str]) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("${" + key + "}", value)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise AssertionError(path.name)
    return parsed


def _wildcard_on_all_resources(policy: dict[str, Any]) -> bool:
    statements = policy["Statement"]
    if not isinstance(statements, list):
        return True
    for statement in statements:
        if not isinstance(statement, dict):
            return True
        actions = _as_list(statement.get("Action"))
        resources = _as_list(statement.get("Resource"))
        if any(action == "*" for action in actions):
            return True
        wildcard_action = any(action.endswith(":*") for action in actions)
        if wildcard_action and any(resource == "*" for resource in resources):
            return True
    return False


def _as_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []
