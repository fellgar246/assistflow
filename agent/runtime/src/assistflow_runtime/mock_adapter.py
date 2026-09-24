"""Mock model adapter. Scripts decide the next proposal; they do not run tools."""

import json
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from assistflow_contracts.agent import (
    AdapterUsage,
    ModelMessage,
    ModelMessageRole,
    ModelResponse,
    ModelText,
    ModelToolUse,
    ScriptedPlan,
    StepKind,
    ToolSchema,
    ToolUseRequest,
)

ScriptSelector = Callable[[str], ScriptedPlan]
FollowUp = Callable[[str, list[dict[str, Any]]], list[Any]]

MOCK_PROVIDER = "mock"
MOCK_MODEL_ID = "mock"


class MockModelAdapter:
    """Return the next scripted text or tool use from the messages already seen."""

    def __init__(self, select_plan: ScriptSelector, follow_up: FollowUp) -> None:
        self._select_plan = select_plan
        self._follow_up = follow_up

    def complete(
        self,
        messages: list[ModelMessage],
        tools: list[ToolSchema],
        max_output_tokens: int,
    ) -> ModelResponse:
        del tools, max_output_tokens
        customer = _latest_user(messages)
        plan = self._select_plan(customer)
        seen = {message.tool_name for message in messages if message.tool_name}
        for step in plan.steps:
            if step.kind is not StepKind.TOOL_PROPOSAL or step.tool_name is None:
                continue
            if step.tool_name in seen:
                continue
            return _tool(step.tool_name, dict(step.arguments))
        pending = self._follow_up(customer, _outcomes(messages))
        for call in pending:
            name = str(getattr(call, "name", ""))
            if name == "" or name in seen:
                continue
            arguments = getattr(call, "arguments", {})
            return _tool(name, dict(arguments) if isinstance(arguments, dict) else {})
        return ModelText(
            text=plan.assistant_message,
            usage=AdapterUsage(input_tokens=0, output_tokens=0),
            provider=MOCK_PROVIDER,
            model_id=MOCK_MODEL_ID,
            latency_ms=0,
        )


def _tool(name: str, arguments: dict[str, Any]) -> ModelToolUse:
    return ModelToolUse(
        requests=[ToolUseRequest(id=uuid4().hex[:12], name=name, arguments=arguments)],
        usage=AdapterUsage(input_tokens=0, output_tokens=0),
        provider=MOCK_PROVIDER,
        model_id=MOCK_MODEL_ID,
        latency_ms=0,
    )


def _latest_user(messages: list[ModelMessage]) -> str:
    for message in reversed(messages):
        if message.role is ModelMessageRole.USER and message.content.strip():
            return message.content
    return ""


def _outcomes(messages: list[ModelMessage]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for message in messages:
        if message.role is not ModelMessageRole.TOOL or message.tool_name is None:
            continue
        try:
            parsed = json.loads(message.content)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            found.append(parsed)
    return found
