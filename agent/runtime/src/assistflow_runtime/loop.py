"""Shared turn loop. The model proposes; this loop validates, runs tier-0 tools, and answers."""

import json
import time
from collections.abc import Callable
from typing import Any, Protocol
from uuid import uuid4

from assistflow_contracts.agent import (
    AgentResult,
    AgentTrace,
    ExecutedTool,
    HistoryMessage,
    ModelMessage,
    ModelMessageRole,
    ModelProviderError,
    ModelResponse,
    ModelText,
    ModelToolUse,
    PromptRef,
    ProposedToolCall,
    StepKind,
    StopReason,
    ToolSchema,
    TraceStep,
    TurnContext,
    Usage,
)

from assistflow_runtime.history import estimate_tokens
from assistflow_runtime.limits import TurnLimits
from assistflow_runtime.prompts import PromptRegistry

# Output beyond the configured token ceiling is rejected. The model text is not stored.
OUTPUT_LIMIT_MESSAGE = (
    "This reply was too long to send. Please narrow the question, or wait for a person."
)
INPUT_LIMIT_MESSAGE = (
    "That message is too long to process. Please send a shorter question, or wait for a person."
)
RETRY_MESSAGE = (
    "I could not finish that request. Please try again in a moment, or wait for a person."
)
BUDGET_MESSAGE = (
    "This request is too broad for one reply. Please narrow it, or wait for a person. "
    "I have not looked up an order, delivery, return, or refund."
)
_SUMMARY_LIMIT = 240

ComposeFacts = Callable[[list[dict[str, Any]]], str]


class ToolGateway(Protocol):
    """Allowlisted schemas and tier-0 execution for one turn."""

    def schemas(self) -> list[ToolSchema]:
        """Schemas the model may see. Tier 3 names are omitted."""

    def execute(self, name: str, arguments: dict[str, Any]) -> ExecutedTool:
        """Run one tier-0 tool. Unknown names and other tiers are denied."""


class ModelAdapterPort(Protocol):
    def complete(
        self,
        messages: list[ModelMessage],
        tools: list[ToolSchema],
        max_output_tokens: int,
    ) -> ModelResponse:
        """Return text, tool use, or a typed provider error."""


class AgentLoop:
    """Call the adapter, execute tier-0 reads, and stop on text or a budget."""

    def __init__(
        self,
        adapter: ModelAdapterPort,
        gateway: ToolGateway,
        prompts: PromptRegistry,
        limits: TurnLimits,
        compose: ComposeFacts,
        *,
        store_debug: bool = False,
    ) -> None:
        self._adapter = adapter
        self._gateway = gateway
        self._prompts = prompts
        self._limits = limits
        self._compose = compose
        self._store_debug = store_debug

    def run(self, turn_context: TurnContext) -> AgentResult:
        prompt = self._prompts.get(turn_context.prompt.id, turn_context.prompt.version)
        if prompt.text.strip() == "":
            raise ValueError("Prompt text is empty.")
        messages = _messages(turn_context.history, turn_context.customer_message)
        if _customer_alone_exceeds(messages, self._limits.max_input_tokens):
            return self._finish(
                turn_context.prompt,
                INPUT_LIMIT_MESSAGE,
                StopReason.FAILED,
                [],
                [],
                Usage(),
                "mock",
                "mock",
            )
        steps: list[TraceStep] = []
        executed: list[ExecutedTool] = []
        proposed: list[ProposedToolCall] = []
        input_tokens = 0
        output_tokens = 0
        model_calls = 0
        provider = "mock"
        model_id = "mock"
        schemas = self._gateway.schemas()
        allowed = {item.name for item in schemas}

        while True:
            if len(steps) >= self._limits.max_agent_steps or (
                model_calls >= self._limits.max_model_calls_per_turn
            ):
                return self._budget(
                    turn_context.prompt,
                    steps,
                    proposed,
                    executed,
                    input_tokens,
                    output_tokens,
                    provider,
                    model_id,
                )
            trimmed = _trim(messages, self._limits.max_input_tokens)
            if trimmed is None:
                return self._finish(
                    turn_context.prompt,
                    INPUT_LIMIT_MESSAGE,
                    StopReason.FAILED,
                    steps,
                    executed,
                    Usage(input_tokens=input_tokens, output_tokens=output_tokens),
                    provider,
                    model_id,
                )
            started = time.perf_counter()
            response = self._adapter.complete(trimmed, schemas, self._limits.max_output_tokens)
            model_calls += 1
            provider = response.provider
            model_id = response.model_id
            input_tokens += response.usage.input_tokens
            output_tokens += response.usage.output_tokens
            latency = response.latency_ms or _elapsed_ms(started)
            if isinstance(response, ModelProviderError):
                steps.append(
                    _step(len(steps), StepKind.MODEL, latency, f"provider {response.code.value}")
                )
                return self._finish(
                    turn_context.prompt,
                    RETRY_MESSAGE,
                    StopReason.FAILED,
                    steps,
                    executed,
                    Usage(input_tokens=input_tokens, output_tokens=output_tokens),
                    provider,
                    model_id,
                )
            if isinstance(response, ModelToolUse):
                steps.append(_step(len(steps), StepKind.MODEL, latency, "model proposed tools"))
                if not self._apply_tools(response, allowed, messages, steps, executed, proposed):
                    return self._budget(
                        turn_context.prompt,
                        steps,
                        proposed,
                        executed,
                        input_tokens,
                        output_tokens,
                        provider,
                        model_id,
                    )
                continue
            text = response.text if isinstance(response, ModelText) else ""
            summary = _model_summary(text, self._store_debug)
            steps.append(_step(len(steps), StepKind.MODEL, latency, summary))
            if _output_exceeds(response, self._limits.max_output_tokens):
                return self._finish(
                    turn_context.prompt,
                    OUTPUT_LIMIT_MESSAGE,
                    StopReason.FAILED,
                    steps,
                    executed,
                    Usage(input_tokens=input_tokens, output_tokens=output_tokens),
                    provider,
                    model_id,
                )
            answer = self._answer(text, executed)
            return self._finish(
                turn_context.prompt,
                answer,
                StopReason.COMPLETED,
                steps,
                executed,
                Usage(input_tokens=input_tokens, output_tokens=output_tokens),
                provider,
                model_id,
                proposed,
            )

    def _apply_tools(
        self,
        response: ModelToolUse,
        allowed: set[str],
        messages: list[ModelMessage],
        steps: list[TraceStep],
        executed: list[ExecutedTool],
        proposed: list[ProposedToolCall],
    ) -> bool:
        """Execute tier-0 proposals. Return false when a cap stops the turn."""
        for request in response.requests:
            if len(steps) >= self._limits.max_agent_steps:
                return False
            if len(executed) >= self._limits.max_tool_calls_per_turn:
                return False
            arguments = request.arguments if isinstance(request.arguments, dict) else {}
            if request.name not in allowed:
                denied = ExecutedTool(
                    name=request.name,
                    status="blocked",
                    error_code="tool_denied",
                    summary="That action is not available.",
                    body=None,
                    risk_level="tier3",
                    arguments_hash="",
                )
                executed.append(denied)
                steps.append(
                    _step(
                        len(steps),
                        StepKind.TOOL_DENIAL,
                        0,
                        f"denied {request.name}",
                    )
                )
                messages.append(_tool_message(request.id, denied))
                continue
            outcome = self._gateway.execute(request.name, arguments)
            executed.append(outcome)
            proposed.append(
                ProposedToolCall(name=request.name, arguments=_plain_arguments(arguments))
            )
            steps.append(_step(len(steps), StepKind.TOOL_PROPOSAL, 0, f"proposed {request.name}"))
            messages.append(_tool_message(request.id, outcome))
        return True

    def _answer(self, model_text: str, executed: list[ExecutedTool]) -> str:
        views = [_view(item) for item in executed if item.status == "succeeded" or item.error_code]
        if any(item.status == "succeeded" and item.body for item in executed):
            return self._compose(views)
        if views:
            composed = self._compose(views)
            if composed:
                return composed
        return model_text if model_text.strip() else OUTPUT_LIMIT_MESSAGE

    def _budget(
        self,
        prompt_ref: PromptRef,
        steps: list[TraceStep],
        proposed: list[ProposedToolCall],
        executed: list[ExecutedTool],
        input_tokens: int,
        output_tokens: int,
        provider: str,
        model_id: str,
    ) -> AgentResult:
        if len(steps) < self._limits.max_agent_steps:
            steps.append(
                _step(len(steps), StepKind.BUDGET, 0, "stopped for a step, tool, or model limit")
            )
        return self._finish(
            prompt_ref,
            BUDGET_MESSAGE,
            StopReason.STOPPED_BUDGET,
            steps,
            executed,
            Usage(input_tokens=input_tokens, output_tokens=output_tokens),
            provider,
            model_id,
            proposed,
        )

    def _finish(
        self,
        prompt_ref: PromptRef,
        assistant_message: str,
        stop_reason: StopReason,
        steps: list[TraceStep],
        executed: list[ExecutedTool],
        usage: Usage,
        provider: str,
        model_id: str,
        proposed: list[ProposedToolCall] | None = None,
    ) -> AgentResult:
        trace_id = uuid4()
        return AgentResult(
            assistant_message=assistant_message,
            proposed_tool_calls=proposed or [],
            trace_id=trace_id,
            stop_reason=stop_reason,
            usage=usage,
            trace=AgentTrace(
                id=trace_id,
                prompt_id=prompt_ref.id,
                prompt_version=prompt_ref.version,
                stop_reason=stop_reason,
                steps=steps,
                provider=provider,
                model_id=model_id,
            ),
            executed_tools=executed,
            tools_handled=True,
        )


def _messages(history: list[HistoryMessage], customer_message: str) -> list[ModelMessage]:
    stored = [
        ModelMessage(
            role=ModelMessageRole.ASSISTANT
            if item.role.value == "assistant"
            else ModelMessageRole.USER,
            content=item.content,
        )
        for item in history
    ]
    stored.append(ModelMessage(role=ModelMessageRole.USER, content=customer_message))
    return stored


def _customer_index(messages: list[ModelMessage]) -> int:
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role is ModelMessageRole.USER and messages[index].tool_name is None:
            return index
    return len(messages) - 1


def _customer_alone_exceeds(messages: list[ModelMessage], token_cap: int) -> bool:
    index = _customer_index(messages)
    return estimate_tokens(messages[index].content) > token_cap


def _trim(messages: list[ModelMessage], token_cap: int) -> list[ModelMessage] | None:
    """Drop the oldest history first. Keep the new customer message."""
    window = list(messages)
    customer_at = _customer_index(window)
    while _token_total(window) > token_cap and customer_at > 0:
        window = window[1:]
        customer_at -= 1
    if _token_total(window) > token_cap:
        return None
    return window


def _token_total(messages: list[ModelMessage]) -> int:
    return sum(estimate_tokens(message.content) for message in messages)


def _output_exceeds(response: ModelResponse, max_output_tokens: int) -> bool:
    if not isinstance(response, ModelText):
        return False
    if response.usage.output_tokens > max_output_tokens:
        return True
    return estimate_tokens(response.text) > max_output_tokens


def _model_summary(text: str, store_debug: bool) -> str:
    if not store_debug:
        return "model returned text"
    cleaned = " ".join(text.split())
    return cleaned[:_SUMMARY_LIMIT] if cleaned else "model returned text"


def _tool_message(tool_call_id: str, outcome: ExecutedTool) -> ModelMessage:
    payload = json.dumps(_view(outcome))
    return ModelMessage(
        role=ModelMessageRole.TOOL,
        content=payload,
        tool_name=outcome.name,
        tool_call_id=tool_call_id,
    )


def _view(outcome: ExecutedTool) -> dict[str, Any]:
    return {
        "name": outcome.name,
        "status": outcome.status,
        "error_code": outcome.error_code,
        "body": outcome.body,
    }


def _plain_arguments(arguments: dict[str, Any]) -> dict[str, str | int | float | bool | None]:
    plain: dict[str, str | int | float | bool | None] = {}
    for key, value in arguments.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            plain[str(key)] = value
    return plain


def _step(index: int, kind: StepKind, latency_ms: int, summary: str) -> TraceStep:
    return TraceStep(
        index=index,
        kind=kind,
        latency_ms=latency_ms,
        input_summary=summary[:_SUMMARY_LIMIT],
    )


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))
