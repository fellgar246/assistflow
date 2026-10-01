"""Shared model loop, mock adapter, and hosted adapter with a fake client."""

from typing import Any
from uuid import uuid4

import pytest
from assistflow_contracts.agent import (
    AdapterUsage,
    ExecutedTool,
    ModelMessage,
    ModelProviderError,
    ModelText,
    ModelToolUse,
    PromptRef,
    ProviderErrorCode,
    ToolSchema,
    ToolUseRequest,
    TurnContext,
)
from assistflow_test_fixtures.agent_scripts import follow_up_calls, select_script

from assistflow_api.config import load_settings, repo_root
from assistflow_runtime.gateway import ToolGateway
from assistflow_runtime.history import estimate_tokens
from assistflow_runtime.hosted_model import HostedModelAdapter
from assistflow_runtime.limits import TurnLimits
from assistflow_runtime.loop import (
    OUTPUT_LIMIT_MESSAGE,
    RETRY_MESSAGE,
    AgentLoop,
)
from assistflow_runtime.mock_adapter import MockModelAdapter
from assistflow_runtime.prompts import PromptRegistry

ORDER_BODY = {
    "order_id": "ORD-10482",
    "status": "paid",
    "total_cents": 4200,
    "currency": "USD",
    "shipping_city": "Austin",
    "shipping_country": "US",
    "shipment": {
        "status": "in_transit",
        "origin_hub": "DFW",
        "estimated_delivery_on": "2099-06-15",
        "carrier_name": "Northline",
    },
}


class OrderGateway:
    def __init__(self) -> None:
        self.executed: list[str] = []

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
        actor_context: object,
    ) -> ExecutedTool:
        del arguments, actor_context
        self.executed.append(name)
        return ExecutedTool(
            name=name,
            status="succeeded",
            summary="get_order succeeded",
            body=dict(ORDER_BODY),
            risk_level="tier0",
            arguments_hash="ab" * 32,
        )


class FakeConverse:
    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _limits(**overrides: int) -> TurnLimits:
    values = {
        "max_agent_steps": 8,
        "max_tool_calls_per_turn": 5,
        "max_model_calls_per_turn": 4,
        "max_output_tokens": 800,
        "max_input_tokens": 6000,
    }
    values.update(overrides)
    return TurnLimits(**values)


def _context(message: str) -> TurnContext:
    return TurnContext(
        tenant_id=uuid4(),
        customer_id=uuid4(),
        conversation_id=uuid4(),
        correlation_id="corr-model",
        customer_message=message,
        history=[],
        prompt=PromptRef(id="local-support", version="1"),
    )


def _loop(
    adapter: Any,
    gateway: ToolGateway | None = None,
    *,
    store_debug: bool = False,
    **limits: int,
) -> AgentLoop:
    return AgentLoop(
        adapter=adapter,
        gateway=gateway or OrderGateway(),
        prompts=PromptRegistry(repo_root() / "agent" / "prompts"),
        limits=_limits(**limits),
        compose=_compose,
        store_debug=store_debug,
    )


def _compose(outcomes: list[dict[str, Any]]) -> str:
    from assistflow_test_fixtures.agent_scripts import reply_from_tools

    return reply_from_tools(outcomes)


def test_mock_order_status_uses_tool_facts() -> None:
    gateway = OrderGateway()
    result = _loop(MockModelAdapter(select_script, follow_up_calls), gateway).run(
        _context("Where is ORD-10482?")
    )

    assert gateway.executed == ["get_order"]
    assert "2099-06-15" in result.assistant_message
    assert "DFW" in result.assistant_message
    assert result.usage.input_tokens == 0
    assert result.usage.output_tokens == 0
    assert result.trace.provider == "mock"
    assert result.trace.model_id == "mock"
    assert result.stop_reason.value == "completed"


def test_fake_hosted_client_executes_get_order_and_ignores_a_wrong_date() -> None:
    client = FakeConverse(
        [
            {
                "output": {
                    "message": {
                        "content": [
                            {
                                "toolUse": {
                                    "toolUseId": "call-1",
                                    "name": "get_order",
                                    "input": {"order_id": "ORD-10482"},
                                }
                            }
                        ]
                    }
                },
                "usage": {"inputTokens": 11, "outputTokens": 4},
            },
            {
                "output": {"message": {"content": [{"text": "Your delivery date is 1999-01-01."}]}},
                "usage": {"inputTokens": 20, "outputTokens": 8},
            },
        ]
    )
    adapter = HostedModelAdapter(client, "configured-model")
    result = _loop(adapter).run(_context("Where is ORD-10482?"))

    assert client.calls[0]["modelId"] == "configured-model"
    assert client.calls[0]["toolConfig"]["tools"][0]["toolSpec"]["name"] == "get_order"
    assert "delete_account" not in str(client.calls[0]["toolConfig"])
    assert "2099-06-15" in result.assistant_message
    assert "1999-01-01" not in result.assistant_message
    assert result.usage.input_tokens == 31
    assert result.usage.output_tokens == 12
    assert result.trace.provider == "bedrock"
    assert result.trace.model_id == "configured-model"
    assert result.trace.steps[0].latency_ms >= 0


def test_model_call_cap_records_usage_up_to_the_limit() -> None:
    class AlwaysTool:
        def __init__(self) -> None:
            self.calls = 0

        def complete(
            self,
            messages: list[ModelMessage],
            tools: list[ToolSchema],
            max_output_tokens: int,
        ) -> ModelToolUse:
            del messages, tools, max_output_tokens
            self.calls += 1
            return ModelToolUse(
                requests=[ToolUseRequest(id=f"c{self.calls}", name="get_order", arguments={})],
                usage=AdapterUsage(input_tokens=3, output_tokens=2),
                provider="bedrock",
                model_id="test-model",
                latency_ms=1,
            )

    adapter = AlwaysTool()
    result = _loop(
        adapter,
        max_model_calls_per_turn=4,
        max_agent_steps=20,
        max_tool_calls_per_turn=20,
    ).run(_context("keep going"))

    assert adapter.calls == 4
    assert result.stop_reason.value == "stopped_budget"
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 8
    assert result.trace.steps[-1].kind.value == "budget"


def test_output_over_the_cap_is_not_stored() -> None:
    class LongText:
        def complete(
            self,
            messages: list[ModelMessage],
            tools: list[ToolSchema],
            max_output_tokens: int,
        ) -> ModelText:
            del messages, tools, max_output_tokens
            return ModelText(
                text="SECRET-OVERFLOW " + ("x" * 20),
                usage=AdapterUsage(input_tokens=1, output_tokens=900),
                provider="bedrock",
                model_id="test-model",
                latency_ms=1,
            )

    result = _loop(LongText(), max_output_tokens=800).run(_context("hello"))
    assert result.assistant_message == OUTPUT_LIMIT_MESSAGE
    assert "SECRET-OVERFLOW" not in result.assistant_message
    assert result.stop_reason.value == "failed"


def test_timeout_throttle_and_malformed_output_fail_safely() -> None:
    class Boom(Exception):
        pass

    timeout = HostedModelAdapter(FakeConverse([TimeoutError("timed out")]), "configured-model")
    timed = _loop(timeout).run(_context("hello"))
    assert timed.assistant_message == RETRY_MESSAGE
    assert timed.stop_reason.value == "failed"

    throttled = HostedModelAdapter(FakeConverse([Boom("ThrottlingException")]), "configured-model")
    held = _loop(throttled).run(_context("hello"))
    assert held.assistant_message == RETRY_MESSAGE
    assert held.trace.stop_reason.value == "failed"

    broken = HostedModelAdapter(FakeConverse([{"output": "nope"}]), "configured-model")
    failed = _loop(broken).run(_context("hello"))
    assert failed.stop_reason.value == "failed"
    assert failed.assistant_message == RETRY_MESSAGE


def test_unknown_tool_is_denied_and_not_executed() -> None:
    class BadTool:
        def complete(
            self,
            messages: list[ModelMessage],
            tools: list[ToolSchema],
            max_output_tokens: int,
        ) -> ModelToolUse | ModelText:
            del tools, max_output_tokens
            if not any(message.tool_name == "delete_account" for message in messages):
                return ModelToolUse(
                    requests=[ToolUseRequest(id="bad", name="delete_account", arguments={})],
                    usage=AdapterUsage(input_tokens=2, output_tokens=1),
                    provider="bedrock",
                    model_id="test-model",
                    latency_ms=1,
                )
            return ModelText(
                text="I cannot do that.",
                usage=AdapterUsage(input_tokens=1, output_tokens=1),
                provider="bedrock",
                model_id="test-model",
                latency_ms=1,
            )

    gateway = OrderGateway()
    result = _loop(BadTool(), gateway).run(_context("delete me"))
    assert gateway.executed == []
    assert any(step.kind.value == "tool_denial" for step in result.trace.steps)
    assert any(item.error_code == "tool_denied" for item in result.executed_tools)


def test_disabled_hosted_model_does_not_construct_a_client(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(region: str) -> object:
        del region
        raise AssertionError("hosted client constructed")

    monkeypatch.setattr("assistflow_runtime.hosted_model.build_hosted_client", _fail)
    from assistflow_api.agents import build_model_adapter

    settings = load_settings({"MODEL_PROVIDER": "bedrock", "BEDROCK_ENABLED": "false"})
    adapter = build_model_adapter(settings)
    assert isinstance(adapter, MockModelAdapter)


def test_customer_message_over_the_input_cap_fails() -> None:
    text = "z" * 40
    assert estimate_tokens(text) > 8
    result = _loop(MockModelAdapter(select_script, follow_up_calls), max_input_tokens=8).run(
        _context(text)
    )
    assert result.stop_reason.value == "failed"
    assert "too long" in result.assistant_message


def test_debug_summary_is_omitted_unless_the_flag_is_on() -> None:
    class Prose:
        def complete(
            self,
            messages: list[ModelMessage],
            tools: list[ToolSchema],
            max_output_tokens: int,
        ) -> ModelText:
            del messages, tools, max_output_tokens
            return ModelText(
                text="raw provider payload should stay out",
                usage=AdapterUsage(input_tokens=1, output_tokens=1),
                provider="bedrock",
                model_id="test-model",
                latency_ms=1,
            )

    hidden = _loop(Prose(), store_debug=False).run(_context("status please"))
    shown = _loop(Prose(), store_debug=True).run(_context("status please"))
    hidden_text = " ".join(step.input_summary for step in hidden.trace.steps)
    shown_text = " ".join(step.input_summary for step in shown.trace.steps)
    assert "raw provider payload" not in hidden_text
    assert "raw provider payload" in shown_text


def test_hosted_error_codes() -> None:
    adapter = HostedModelAdapter(FakeConverse([TimeoutError("timeout")]), "m")
    result = adapter.complete([], [], 10)
    assert isinstance(result, ModelProviderError)
    assert result.code is ProviderErrorCode.TIMEOUT
