"""Scripted assistant runner. It records a trace and enforces turn caps in-process."""

import re
import time
from collections.abc import Callable
from uuid import uuid4

from assistflow_contracts.agent import (
    AgentResult,
    AgentTrace,
    PromptRef,
    ProposedToolCall,
    ScriptedPlan,
    ScriptedStep,
    StepKind,
    StopReason,
    TraceStep,
    TurnContext,
    Usage,
)

from assistflow_runtime.limits import TurnLimits
from assistflow_runtime.prompts import PromptRegistry

BUDGET_MESSAGE = (
    "This request is too broad for one reply. Please narrow it, or wait for a person. "
    "I have not looked up an order, delivery, return, or refund."
)

_SECRET_MARKERS = ("token", "password", "secret", "authorization", "api_key")
_SECRET_VALUE = re.compile(r"(?i)\b(token|password|secret|api_key|authorization)\b\s*[:=]\s*\S+")
_ORDER_NUMBER = re.compile(r"^ORD-\d+$")
_SUMMARY_LIMIT = 240

ScriptSelector = Callable[[str], ScriptedPlan]


class MockAgentRunner:
    """Select a scripted plan and stop when a step, tool, or model cap is reached.

    Proposed tool calls are not executed. Latency is the in-process elapsed time.
    This runner does not sleep and does not call a model.
    """

    def __init__(
        self,
        prompts: PromptRegistry,
        limits: TurnLimits,
        select_plan: ScriptSelector,
    ) -> None:
        self._prompts = prompts
        self._limits = limits
        self._select_plan = select_plan

    def run(self, turn_context: TurnContext) -> AgentResult:
        prompt = self._prompts.get(turn_context.prompt.id, turn_context.prompt.version)
        plan = self._select_plan(turn_context.customer_message)
        recorded: list[TraceStep] = []
        proposed: list[ProposedToolCall] = []
        model_calls = 0
        tool_calls = 0

        for offset, planned in enumerate(plan.steps):
            if planned.kind is StepKind.BUDGET:
                raise ValueError("A script cannot plan a budget step.")
            if len(recorded) >= self._limits.max_agent_steps:
                return self._stopped(turn_context.prompt, recorded, proposed)
            blocked = _blocked(planned, model_calls, tool_calls, self._limits)
            more_after = offset < len(plan.steps) - 1
            last_slot = len(recorded) + 1 >= self._limits.max_agent_steps
            if blocked or (last_slot and more_after):
                return self._stopped(turn_context.prompt, recorded, proposed)
            recorded.append(_record_step(len(recorded), planned))
            if planned.kind is StepKind.MODEL:
                model_calls += 1
            else:
                tool_calls += 1
                if planned.tool_name is None:
                    raise ValueError("A tool proposal needs a tool name.")
                proposed.append(
                    ProposedToolCall(name=planned.tool_name, arguments=dict(planned.arguments))
                )
        return _result(
            prompt_ref=turn_context.prompt,
            assistant_message=plan.assistant_message,
            proposed=proposed,
            stop_reason=StopReason.COMPLETED,
            steps=recorded,
            prompt_text=prompt.text,
        )

    def _stopped(
        self,
        prompt_ref: PromptRef,
        recorded: list[TraceStep],
        proposed: list[ProposedToolCall],
    ) -> AgentResult:
        if len(recorded) < self._limits.max_agent_steps:
            recorded.append(
                TraceStep(
                    index=len(recorded),
                    kind=StepKind.BUDGET,
                    latency_ms=0,
                    input_summary="stopped for a step, tool, or model limit",
                )
            )
        loaded = self._prompts.get(prompt_ref.id, prompt_ref.version)
        return _result(
            prompt_ref=prompt_ref,
            assistant_message=BUDGET_MESSAGE,
            proposed=proposed,
            stop_reason=StopReason.STOPPED_BUDGET,
            steps=recorded,
            prompt_text=loaded.text,
        )


def _blocked(planned: ScriptedStep, model_calls: int, tool_calls: int, limits: TurnLimits) -> bool:
    if planned.kind is StepKind.MODEL:
        return model_calls >= limits.max_model_calls_per_turn
    return tool_calls >= limits.max_tool_calls_per_turn


def _record_step(index: int, planned: ScriptedStep) -> TraceStep:
    started = time.perf_counter()
    if planned.kind is StepKind.TOOL_PROPOSAL:
        summary = _tool_summary(planned.tool_name or "tool", planned.arguments)
    else:
        summary = _redact(planned.summary)
    return TraceStep(
        index=index,
        kind=planned.kind,
        latency_ms=_elapsed_ms(started),
        input_summary=summary,
    )


def _result(
    *,
    prompt_ref: PromptRef,
    assistant_message: str,
    proposed: list[ProposedToolCall],
    stop_reason: StopReason,
    steps: list[TraceStep],
    prompt_text: str,
) -> AgentResult:
    if prompt_text.strip() == "":
        raise ValueError("Prompt text is empty.")
    trace_id = uuid4()
    return AgentResult(
        assistant_message=assistant_message,
        proposed_tool_calls=proposed,
        trace_id=trace_id,
        stop_reason=stop_reason,
        usage=Usage(input_tokens=0, output_tokens=0),
        trace=AgentTrace(
            id=trace_id,
            prompt_id=prompt_ref.id,
            prompt_version=prompt_ref.version,
            stop_reason=stop_reason,
            steps=steps,
        ),
    )


def _tool_summary(name: str, arguments: dict[str, str | int | float | bool | None]) -> str:
    parts: list[str] = []
    for key, value in arguments.items():
        if any(marker in key.lower() for marker in _SECRET_MARKERS):
            continue
        if isinstance(value, str) and _ORDER_NUMBER.fullmatch(value):
            parts.append(f"{key}={value}")
    suffix = f" {', '.join(parts)}" if parts else ""
    return _redact(f"proposed {name}{suffix}")


def _redact(text: str) -> str:
    cleaned = _SECRET_VALUE.sub("[redacted]", text)
    return cleaned[:_SUMMARY_LIMIT]


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))
