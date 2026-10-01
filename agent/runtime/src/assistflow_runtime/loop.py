"""Shared turn loop.

The model proposes. This loop validates, runs allowlisted tools, and answers.
"""

import json
import logging
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
from assistflow_contracts.conversation import Citation
from assistflow_contracts.gateway import GatewayActor, is_allowlisted_tool

from assistflow_runtime.gateway import ToolGateway
from assistflow_runtime.guardrails import (
    DENIED_TOPIC_MESSAGE,
    GUARDRAIL_UNAVAILABLE_MESSAGE,
    GuardrailAction,
    GuardrailDecision,
    GuardrailFilter,
    NoOpGuardrailFilter,
    customer_text_after_guardrail,
    reveals_system_prompt,
)
from assistflow_runtime.history import estimate_tokens
from assistflow_runtime.limits import TurnLimits
from assistflow_runtime.prompts import PromptRegistry
from assistflow_runtime.redaction import redact_data, redact_text

_LOGGER = logging.getLogger("assistflow.turn")

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
ABSTAIN_MESSAGE = "I do not have enough verified information to answer."
_RETRIEVAL_TOOL = "search_support_policy"
_SUMMARY_LIMIT = 240

ComposeFacts = Callable[[list[dict[str, Any]]], str]


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
        guardrail: GuardrailFilter | None = None,
    ) -> None:
        self._adapter = adapter
        self._gateway = gateway
        self._prompts = prompts
        self._limits = limits
        self._compose = compose
        self._store_debug = store_debug
        self._guardrail = guardrail if guardrail is not None else NoOpGuardrailFilter()

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
        retrievals = 0
        input_tokens = 0
        output_tokens = 0
        model_calls = 0
        provider = "mock"
        model_id = "mock"
        actor = _actor(turn_context)
        schemas = [item for item in self._gateway.list_tools() if is_allowlisted_tool(item.name)]
        allowed = {item.name for item in schemas}
        decision, model_calls = self._screen(
            "input", turn_context.customer_message, model_calls, steps
        )
        if decision.action is GuardrailAction.BLOCK:
            return self._refusal(
                turn_context.prompt, DENIED_TOPIC_MESSAGE, StopReason.COMPLETED, steps
            )
        if decision.action is GuardrailAction.UNAVAILABLE:
            return self._refusal(
                turn_context.prompt,
                GUARDRAIL_UNAVAILABLE_MESSAGE,
                StopReason.FAILED,
                steps,
            )
        if decision.action is GuardrailAction.REDACT and decision.text.strip():
            messages = _messages(turn_context.history, decision.text)

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
                applied, retrievals = self._apply_tools(
                    response,
                    allowed,
                    actor,
                    messages,
                    steps,
                    executed,
                    proposed,
                    retrievals,
                )
                if not applied:
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
            summary = (
                "model output withheld"
                if reveals_system_prompt(text, prompt.text)
                else _model_summary(text, self._store_debug)
            )
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
            answer, citations, failures = self._ground(text, executed)
            from_tools = any(item.status == "succeeded" and item.body for item in executed)
            decision, model_calls = self._screen("output", answer, model_calls, steps)
            customer_text, failed = customer_text_after_guardrail(
                answer,
                prompt.text,
                from_tools=from_tools,
                decision=decision,
            )
            return self._finish(
                turn_context.prompt,
                customer_text,
                StopReason.FAILED if failed else StopReason.COMPLETED,
                steps,
                executed,
                Usage(input_tokens=input_tokens, output_tokens=output_tokens),
                provider,
                model_id,
                proposed,
                citations,
                failures,
            )

    def _apply_tools(
        self,
        response: ModelToolUse,
        allowed: set[str],
        actor: GatewayActor,
        messages: list[ModelMessage],
        steps: list[TraceStep],
        executed: list[ExecutedTool],
        proposed: list[ProposedToolCall],
        retrievals: int,
    ) -> tuple[bool, int]:
        """Execute allowlisted proposals. Tier 2 names are denied here. Return false at a cap."""
        for request in response.requests:
            if len(steps) >= self._limits.max_agent_steps:
                return False, retrievals
            if len(executed) >= self._limits.max_tool_calls_per_turn:
                return False, retrievals
            if request.name == _RETRIEVAL_TOOL:
                if retrievals >= self._limits.max_retrievals_per_turn:
                    return False, retrievals
                retrievals += 1
            arguments = request.arguments if isinstance(request.arguments, dict) else {}
            if request.name not in allowed:
                denied = _redacted_tool(
                    ExecutedTool(
                        name=request.name,
                        status="blocked",
                        error_code="tool_denied",
                        summary="That action is not available.",
                        body=None,
                        risk_level="tier3",
                        arguments_hash="",
                    )
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
            outcome = _redacted_tool(self._gateway.call_tool(request.name, arguments, actor))
            executed.append(outcome)
            proposed.append(
                ProposedToolCall(name=request.name, arguments=_plain_arguments(arguments))
            )
            steps.append(_step(len(steps), StepKind.TOOL_PROPOSAL, 0, f"proposed {request.name}"))
            messages.append(_tool_message(request.id, outcome))
        return True, retrievals

    def _screen(
        self,
        source: str,
        text: str,
        model_calls: int,
        steps: list[TraceStep],
    ) -> tuple[GuardrailDecision, int]:
        """Inspect text. An enabled filter counts as one model call and never gets skipped."""
        if not self._guardrail.consumes_model_call():
            decision = (
                self._guardrail.inspect_output(text)
                if source == "output"
                else self._guardrail.inspect_input(text)
            )
            return decision, model_calls
        if (
            model_calls >= self._limits.max_model_calls_per_turn
            or len(steps) >= self._limits.max_agent_steps
        ):
            return (
                GuardrailDecision(GuardrailAction.UNAVAILABLE, GUARDRAIL_UNAVAILABLE_MESSAGE),
                model_calls,
            )
        started = time.perf_counter()
        try:
            decision = (
                self._guardrail.inspect_output(text)
                if source == "output"
                else self._guardrail.inspect_input(text)
            )
        except Exception:
            decision = GuardrailDecision(GuardrailAction.UNAVAILABLE, GUARDRAIL_UNAVAILABLE_MESSAGE)
        steps.append(
            _step(
                len(steps),
                StepKind.GUARDRAIL,
                _elapsed_ms(started),
                f"guardrail {decision.action.value}",
            )
        )
        return decision, model_calls + 1

    def _refusal(
        self,
        prompt_ref: PromptRef,
        message: str,
        stop_reason: StopReason,
        steps: list[TraceStep],
    ) -> AgentResult:
        return self._finish(
            prompt_ref,
            message,
            stop_reason,
            steps,
            [],
            Usage(),
            "mock",
            "mock",
        )

    def _ground(
        self, model_text: str, executed: list[ExecutedTool]
    ) -> tuple[str, list[Citation], int]:
        """Answer policy turns from retrieved chunks. Weak retrieval abstains."""
        retrievals = [
            item for item in executed if item.name == _RETRIEVAL_TOOL and item.status == "succeeded"
        ]
        if not retrievals:
            return self._answer(model_text, executed), [], 0
        chunks = _chunks(retrievals)
        if not chunks:
            return ABSTAIN_MESSAGE, [], 1
        parts: list[str] = []
        citations: list[Citation] = []
        for index, chunk in enumerate(chunks, start=1):
            parts.append(f"{chunk['text'].strip()} [{index}]")
            citations.append(Citation(title=chunk["title"], version=str(chunk["version"])))
        return " ".join(parts), citations, 0

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
        citations: list[Citation] | None = None,
        grounded_answer_failures: int = 0,
    ) -> AgentResult:
        trace_id = uuid4()
        assistant_message = redact_text(assistant_message)
        if assistant_message.strip() == "":
            assistant_message = DENIED_TOPIC_MESSAGE
        safe_steps = [
            step.model_copy(
                update={"input_summary": redact_text(step.input_summary)[:_SUMMARY_LIMIT]}
            )
            for step in steps
        ]
        safe_executed = [_redacted_tool(item) for item in executed]
        _LOGGER.info(
            "turn_finished stop_reason=%s assistant_message=%s tool_summaries=%s",
            stop_reason.value,
            assistant_message,
            " | ".join(item.summary for item in safe_executed),
        )
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
                steps=safe_steps,
                provider=provider,
                model_id=model_id,
                grounded_answer_failures=grounded_answer_failures,
            ),
            executed_tools=safe_executed,
            tools_handled=True,
            citations=citations or [],
            grounded_answer_failures=grounded_answer_failures,
        )


def _actor(turn_context: TurnContext) -> GatewayActor:
    return GatewayActor(
        tenant_id=turn_context.tenant_id,
        customer_id=turn_context.customer_id,
        actor_type=turn_context.actor_type,
        correlation_id=turn_context.correlation_id,
        conversation_id=turn_context.conversation_id,
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
    cleaned = " ".join(redact_text(text).split())
    return cleaned[:_SUMMARY_LIMIT] if cleaned else "model returned text"


def _redacted_tool(outcome: ExecutedTool) -> ExecutedTool:
    body = redact_data(outcome.body) if outcome.body is not None else None
    redacted_body = body if isinstance(body, dict) else None
    return outcome.model_copy(
        update={
            "summary": redact_text(outcome.summary)[:_SUMMARY_LIMIT],
            "body": redacted_body,
        }
    )


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
        "body": _untrusted_body(outcome),
    }


def _untrusted_body(outcome: ExecutedTool) -> dict[str, Any] | None:
    """Wrap retrieved article text so the model treats it as data."""
    body = outcome.body
    if outcome.name != _RETRIEVAL_TOOL or not isinstance(body, dict):
        return body
    wrapped: list[dict[str, Any]] = []
    raw_chunks = body.get("chunks")
    if isinstance(raw_chunks, list):
        for chunk in raw_chunks:
            if not isinstance(chunk, dict):
                continue
            copied = dict(chunk)
            text = str(copied.get("text", ""))
            copied["text"] = f"<untrusted_document>\n{text}\n</untrusted_document>"
            wrapped.append(copied)
    return {**body, "chunks": wrapped}


def _chunks(executed: list[ExecutedTool]) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for item in executed:
        body = item.body if isinstance(item.body, dict) else {}
        raw = body.get("chunks")
        if not isinstance(raw, list):
            continue
        for chunk in raw:
            if not isinstance(chunk, dict):
                continue
            title = chunk.get("title")
            text = chunk.get("text")
            version = chunk.get("version")
            if isinstance(title, str) and isinstance(text, str) and text.strip():
                found.append({"title": title, "text": text, "version": str(version)})
    return found


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
