"""Local-only hard stop, quotas before provider calls, cost counters, and cleanup."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import structlog
from assistflow_contracts.agent import (
    AdapterUsage,
    ExecutedTool,
    ModelMessage,
    ModelResponse,
    ModelText,
    PromptRef,
    ToolSchema,
    TurnContext,
)
from assistflow_contracts.gateway import GatewayActor
from assistflow_conversations.commands import ACKNOWLEDGEMENT
from assistflow_runtime.gateway import AgentCoreToolGateway
from assistflow_runtime.limits import TurnLimits
from assistflow_runtime.loop import AgentLoop
from assistflow_runtime.mock_adapter import MockModelAdapter
from assistflow_runtime.prompts import PromptRegistry
from assistflow_runtime.quota import (
    TOKEN_QUOTA_MESSAGE,
    ExecutionQuota,
    QuotaLimits,
    memory_event_allowed,
    provider_refusal,
)
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from assistflow_api.agents import build_model_adapter
from assistflow_api.config import ModelProvider, load_settings, repo_root
from assistflow_api.logging import (
    bind_success_sampling,
    configure_logging,
    reset_success_sampling,
)
from assistflow_api.main import create_app
from tokens import HARBOR, HARBOR_CUSTOMER, NORA, customer_headers, staff_headers

_CLEANUP = repo_root() / "scripts" / "cleanup_tagged.py"


class SpyAdapter:
    """Records provider calls and returns a short reply."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(
        self,
        messages: list[ModelMessage],
        tools: list[ToolSchema],
        max_output_tokens: int,
    ) -> ModelResponse:
        del messages, tools, max_output_tokens
        self.calls += 1
        return ModelText(
            text="I can help with an order number.",
            usage=AdapterUsage(input_tokens=4, output_tokens=3),
            provider="mock",
            model_id="mock",
        )


class RecordingTransport:
    def __init__(self) -> None:
        self.calls = 0

    def request(
        self,
        method: str,
        params: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        del method, params, headers
        self.calls += 1
        return {"result": {"isError": False, "content": [{"type": "text", "text": "{}"}]}}


def test_local_only_serves_health_order_and_acknowledgement_without_clients(
    support_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed: list[str] = []

    def client(name: str, **_kwargs: object) -> object:
        constructed.append(name)
        return object()

    fake = types.ModuleType("boto3")
    fake.client = client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "boto3", fake)
    settings = load_settings(
        {
            "LOCAL_ONLY_MODE": "true",
            "AWS_ENABLED": "true",
            "AGENTCORE_ENABLED": "true",
            "BEDROCK_ENABLED": "true",
            "MANAGED_RAG_ENABLED": "true",
            "LONG_TERM_MEMORY_ENABLED": "true",
            "GUARDRAILS_ENABLED": "true",
            "AI_ENABLED": "true",
            "MODEL_PROVIDER": "bedrock",
            "RAG_PROVIDER": "managed",
            "AGENTCORE_RUNTIME_ARN": (
                "arn:aws:bedrock-agentcore:us-east-1:000000000000:runtime/assistflow"
            ),
            "AGENTCORE_MEMORY_ID": "memory",
            "MANAGED_KNOWLEDGE_BASE_ID": "kb",
            "MANAGED_RAG_METADATA_KEY": "tenant_id",
        }
    )
    assert settings.ai_enabled is False
    assert settings.model_provider is ModelProvider.MOCK
    assert isinstance(build_model_adapter(settings), MockModelAdapter)
    app = create_app(settings, engine=support_engine)
    with TestClient(app) as client_http:
        health = client_http.get("/health")
        headers = customer_headers(client_http, HARBOR, HARBOR_CUSTOMER)
        order = client_http.get("/orders/ORD-10482", headers=headers)
        created = client_http.post(
            "/conversations",
            headers=headers,
            json={"idempotency_key": "local-only-conv"},
        )
        conversation_id = created.json()["id"]
        client_http.post(
            f"/conversations/{conversation_id}/messages",
            headers=headers,
            json={"content": "Where is ORD-10482?", "idempotency_key": "local-only-msg"},
        )
        transcript = client_http.get(
            f"/conversations/{conversation_id}/messages",
            headers=headers,
        )

    assert health.status_code == 200
    assert health.json()["status"] == "healthy"
    assert order.status_code == 200
    assert order.json()["order_number"] == "ORD-10482"
    contents = [item["content"] for item in transcript.json()["items"]]
    assert contents == ["Where is ORD-10482?", ACKNOWLEDGEMENT]
    assert constructed == []


def test_session_quota_returns_a_typed_error_before_the_model(
    support_engine: Engine,
) -> None:
    settings = load_settings({"MAX_SESSIONS_PER_DAY": "1"})
    app = create_app(settings, engine=support_engine)
    spy = SpyAdapter()
    app.state.model_adapter = spy
    with TestClient(app) as client:
        headers = customer_headers(client, HARBOR, HARBOR_CUSTOMER)
        first = _send(client, headers, "quota-a", "Hello")
        second = _send(client, headers, "quota-b", "Hello again")

    assert first.status_code == 201
    assert second.status_code == 429
    assert second.json()["code"] == "session_quota_exceeded"
    assert spy.calls == 1


def test_ai_kill_switch_skips_the_model_while_aws_stays_on(support_engine: Engine) -> None:
    settings = load_settings(
        {
            "AWS_ENABLED": "true",
            "AGENTCORE_ENABLED": "true",
            "BEDROCK_ENABLED": "true",
            "AI_ENABLED": "false",
        }
    )
    assert settings.aws_enabled is True
    app = create_app(settings, engine=support_engine)
    spy = SpyAdapter()
    app.state.model_adapter = spy
    with TestClient(app) as client:
        headers = customer_headers(client, HARBOR, HARBOR_CUSTOMER)
        order = client.get("/orders/ORD-10482", headers=headers)
        sent = _send(client, headers, "ai-off", "Can you help?")
        transcript = client.get(
            f"/conversations/{sent.headers['X-Conversation-Id']}/messages",
            headers=headers,
        )

    assert order.status_code == 200
    assert order.json()["order_number"] == "ORD-10482"
    assert sent.status_code == 201
    assert spy.calls == 0
    contents = [item["content"] for item in transcript.json()["items"]]
    assert ACKNOWLEDGEMENT in contents


def test_token_ceiling_refuses_before_the_provider() -> None:
    assert (
        provider_refusal(6001, 800, max_input_tokens=6000, max_output_tokens=800)
        == TOKEN_QUOTA_MESSAGE
    )
    spy = SpyAdapter()

    class IdleGateway:
        def list_tools(self) -> list[ToolSchema]:
            return []

        def call_tool(
            self,
            name: str,
            arguments: dict[str, Any],
            actor_context: GatewayActor | None,
        ) -> ExecutedTool:
            del name, arguments, actor_context
            raise AssertionError("A tool call started after the token ceiling.")

    loop = AgentLoop(
        spy,
        IdleGateway(),
        PromptRegistry(repo_root() / "agent" / "prompts"),
        TurnLimits(
            max_agent_steps=8,
            max_tool_calls_per_turn=5,
            max_model_calls_per_turn=4,
            max_output_tokens=800,
            max_input_tokens=1,
        ),
        _empty_reply,
    )
    result = loop.run(
        TurnContext(
            tenant_id=HARBOR,
            customer_id=HARBOR_CUSTOMER,
            conversation_id=uuid4(),
            correlation_id="corr-tokens",
            customer_message="This question is longer than one token.",
            history=[],
            prompt=PromptRef(id="local-support", version="1"),
        )
    )

    assert spy.calls == 0
    assert result.assistant_message


def test_gateway_session_cap_stops_before_the_hosted_call() -> None:
    transport = RecordingTransport()
    quota = ExecutionQuota(QuotaLimits(max_tool_calls_per_session=1))
    gateway = AgentCoreToolGateway(
        transport,
        inbound_token="token",
        context_secret="secret",
        tool_quota=quota,
    )
    actor = GatewayActor(
        tenant_id=HARBOR,
        customer_id=HARBOR_CUSTOMER,
        actor_type="customer",
        correlation_id="corr-tools",
        conversation_id=uuid4(),
    )
    first = gateway.call_tool("get_order", {"order_id": "ORD-10482"}, actor)
    second = gateway.call_tool("get_order", {"order_id": "ORD-10482"}, actor)

    assert first.error_code != "tool_quota_exceeded"
    assert second.status == "blocked"
    assert second.error_code == "tool_quota_exceeded"
    assert transport.calls == 1
    assert not memory_event_allowed(30, 30)
    assert memory_event_allowed(29, 30)


def test_staff_cost_counters_are_hidden_from_customers(support_client: TestClient) -> None:
    customer = support_client.get(
        "/staff/cost",
        headers=customer_headers(support_client, HARBOR, HARBOR_CUSTOMER),
    )
    assert customer.status_code == 403

    _send(
        support_client,
        customer_headers(support_client, HARBOR, HARBOR_CUSTOMER),
        "cost-conv",
        "Hello",
    )
    staff = support_client.get(
        "/staff/cost",
        headers=staff_headers(support_client, HARBOR, NORA),
    )

    assert staff.status_code == 200
    body = staff.json()
    assert body["sessions"] >= 1
    assert body["max_sessions_per_day"] == 25
    assert body["input_tokens"] >= 0
    assert body["output_tokens"] >= 0
    assert body["tool_calls"] >= 0
    assert body["max_tool_calls_per_session"] == 15
    assert body["budget_console_url"].startswith("https://console.aws.amazon.com/billing/")


def test_aws_demo_keeps_failure_correlation_and_shortens_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging()
    token = bind_success_sampling(True)
    try:
        logger = structlog.get_logger("assistflow.trace")
        logger.info(
            "trace_hop",
            correlation_id="corr-ok",
            status="succeeded",
            tool_name="get_order",
            latency_ms=12,
        )
        logger.error(
            "trace_hop",
            correlation_id="corr-fail",
            status="failed",
            error_code="tool_failed",
            tool_name="get_order",
        )
    finally:
        reset_success_sampling(token)

    output = capsys.readouterr().out
    success, failure = output.split("corr-fail", maxsplit=1)
    assert "get_order" not in success
    assert "corr-ok" in success
    assert "corr-fail" in output
    assert "tool_failed" in failure
    assert "get_order" in failure


def test_cleanup_dry_run_lists_tagged_resources_and_deletes_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _cleanup()
    deleted: list[str] = []
    kept = "arn:aws:lambda:us-east-1:000000000000:function:assistflow-dev-api"
    code = module.run_cleanup(
        environment="dev",
        execute=False,
        resources=[
            module.TaggedResource(
                arn=kept,
                tags={"Project": "assistflow", "AutoCleanup": "true", "Environment": "dev"},
            ),
            module.TaggedResource(
                arn="arn:aws:lambda:us-east-1:000000000000:function:other",
                tags={"Project": "other", "AutoCleanup": "true", "Environment": "dev"},
            ),
        ],
        delete=deleted.append,
    )

    output = capsys.readouterr().out
    assert code == 0
    assert deleted == []
    assert kept in output
    assert "Project=assistflow" in output
    assert "AutoCleanup=true" in output
    assert "Dry run. Nothing was deleted." in output
    assert "function:other" not in output


def test_cleanup_refuses_a_non_dev_environment() -> None:
    module = _cleanup()
    deleted: list[str] = []
    code = module.run_cleanup(
        environment="prod",
        execute=True,
        resources=[
            module.TaggedResource(
                arn="arn:aws:lambda:us-east-1:000000000000:function:assistflow-dev-api",
                tags={"Project": "assistflow", "AutoCleanup": "true", "Environment": "dev"},
            )
        ],
        delete=deleted.append,
    )
    refused = module.main(["--environment", "staging", "--execute"], {})

    assert code == 2
    assert refused == 2
    assert deleted == []


def test_cleanup_execute_deletes_only_project_resources() -> None:
    module = _cleanup()
    deleted: list[str] = []
    match = "arn:aws:lambda:us-east-1:000000000000:function:assistflow-dev-api"
    code = module.run_cleanup(
        environment="dev",
        execute=True,
        resources=[
            module.TaggedResource(
                arn=match,
                tags={"Project": "assistflow", "AutoCleanup": "true", "Environment": "dev"},
            ),
            module.TaggedResource(
                arn="arn:aws:lambda:us-east-1:000000000000:function:foreign",
                tags={"Project": "assistflow", "AutoCleanup": "false", "Environment": "dev"},
            ),
        ],
        delete=deleted.append,
    )

    assert code == 0
    assert deleted == [match]


def test_gateway_configuration_renders_the_session_tool_cap() -> None:
    module = (repo_root() / "infra" / "modules" / "agentcore_gateway" / "main.tf").read_text(
        encoding="utf-8"
    )
    variables = (
        repo_root() / "infra" / "modules" / "agentcore_gateway" / "variables.tf"
    ).read_text(encoding="utf-8")
    assert "MAX_TOOL_CALLS_PER_SESSION" in module
    assert "tostring(var.max_tool_calls_per_session)" in module
    assert "control plane has no per-session throttle" in module
    assert "default     = 15" in variables


def test_log_groups_keep_fourteen_days_or_shorter() -> None:
    infra = repo_root() / "infra"
    groups = [
        path
        for path in infra.rglob("*.tf")
        if 'resource "aws_cloudwatch_log_group"' in path.read_text(encoding="utf-8")
    ]
    assert groups
    for path in groups:
        assert "retention_in_days" in path.read_text(encoding="utf-8")
    for path in infra.rglob("variables.tf"):
        text = path.read_text(encoding="utf-8")
        if 'variable "log_retention_days"' not in text:
            continue
        assert "default     = 14" in text
        assert "<= 14" in text


def test_deployed_task_kill_switches_stay_off() -> None:
    module = _operator()
    configuration = {
        "Environment": {
            "Variables": {
                "LOCAL_ONLY_MODE": "true",
                "AWS_ENABLED": "false",
                "AGENTCORE_ENABLED": "false",
                "BEDROCK_ENABLED": "false",
                "MANAGED_RAG_ENABLED": "false",
                "LONG_TERM_MEMORY_ENABLED": "false",
                "GUARDRAILS_ENABLED": "false",
                "AI_ENABLED": "false",
            }
        }
    }
    assert module.kill_switches_off(configuration) is True
    configuration["Environment"]["Variables"]["BEDROCK_ENABLED"] = "true"
    assert module.kill_switches_off(configuration) is False
    task = (repo_root() / "infra" / "modules" / "api" / "main.tf").read_text(encoding="utf-8")
    for name in module.KILL_SWITCH_ENV:
        assert name in task


def _empty_reply(_facts: list[dict[str, Any]]) -> str:
    return ""


def _send(client: TestClient, headers: dict[str, str], key: str, content: str) -> Any:
    created = client.post(
        "/conversations",
        headers=headers,
        json={"idempotency_key": f"{key}-conv"},
    )
    assert created.status_code == 201, created.text
    return client.post(
        f"/conversations/{created.json()['id']}/messages",
        headers=headers,
        json={"content": content, "idempotency_key": f"{key}-msg"},
    )


def _cleanup() -> Any:
    return _load(_CLEANUP, "cleanup_tagged")


def _operator() -> Any:
    return _load(repo_root() / "scripts" / "dev_environment.py", "dev_environment_cost")


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    loader = spec.loader
    assert loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module
