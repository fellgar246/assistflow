"""Turn, result, and trace contracts for the assistant runner.

This module performs no input or output. It does not carry cloud clients.
"""

from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from assistflow_contracts.conversation import MessageRole


class StopReason(StrEnum):
    COMPLETED = "completed"
    STOPPED_BUDGET = "stopped_budget"


class StepKind(StrEnum):
    MODEL = "model"
    TOOL_PROPOSAL = "tool_proposal"
    BUDGET = "budget"


class PromptRef(BaseModel):
    """Identifies the prompt text that should guide one turn."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=1, max_length=40)


class HistoryMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: MessageRole
    content: str


class TurnContext(BaseModel):
    """One customer turn. History is already bounded by the caller."""

    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    customer_id: UUID
    conversation_id: UUID
    correlation_id: str = Field(min_length=1, max_length=200)
    customer_message: str = Field(min_length=1)
    history: list[HistoryMessage]
    prompt: PromptRef


class ProposedToolCall(BaseModel):
    """A tool the assistant wants to run. This contract does not execute it."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=80)
    arguments: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class Usage(BaseModel):
    """Token counters. A local scripted turn may leave both at zero."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class TraceStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=0)
    kind: StepKind
    latency_ms: int = Field(ge=0)
    input_summary: str = Field(max_length=240)


class AgentTrace(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    prompt_id: str
    prompt_version: str
    stop_reason: StopReason
    steps: list[TraceStep]


class AgentResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    assistant_message: str = Field(min_length=1)
    proposed_tool_calls: list[ProposedToolCall]
    trace_id: UUID
    stop_reason: StopReason
    usage: Usage
    trace: AgentTrace


class ScriptedStep(BaseModel):
    """One planned step. Budget steps are recorded by the runner, not by a script."""

    model_config = ConfigDict(frozen=True)

    kind: StepKind
    summary: str = Field(min_length=1, max_length=240)
    tool_name: str | None = Field(default=None, max_length=80)
    arguments: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class ScriptedPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    assistant_message: str = Field(min_length=1)
    steps: list[ScriptedStep]


class AgentRunner(Protocol):
    """Port the API calls for one turn. Implementations must not require a cloud SDK."""

    def run(self, turn_context: TurnContext) -> AgentResult:
        """Run one turn and return the public result."""
