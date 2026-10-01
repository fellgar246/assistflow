"""Turn, result, and trace contracts for the assistant runner.

This module performs no input or output. It does not carry cloud clients.
"""

from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from assistflow_contracts.conversation import Citation, MessageRole
from assistflow_contracts.memory import MemoryPreference, SessionFacts


class StopReason(StrEnum):
    COMPLETED = "completed"
    STOPPED_BUDGET = "stopped_budget"
    FAILED = "failed"


class StepKind(StrEnum):
    MODEL = "model"
    TOOL_PROPOSAL = "tool_proposal"
    TOOL_DENIAL = "tool_denial"
    BUDGET = "budget"
    GUARDRAIL = "guardrail"


class ProviderErrorCode(StrEnum):
    TIMEOUT = "timeout"
    THROTTLED = "throttled"
    MALFORMED = "malformed"


class ModelMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


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
    actor_type: str = Field(default="customer", min_length=1, max_length=32)
    session_memory: SessionFacts | None = None
    preferences: list[MemoryPreference] = Field(default_factory=list)


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
    provider: str = "mock"
    model_id: str = "mock"
    grounded_answer_failures: int = Field(default=0, ge=0)
    runtime_invocation_id: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)


class ScriptedStep(BaseModel):
    """One planned step. Budget steps are recorded by the runner, not by a script."""

    model_config = ConfigDict(frozen=True)

    kind: StepKind
    summary: str = Field(min_length=1, max_length=240)
    tool_name: str | None = Field(default=None, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ScriptedPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    assistant_message: str = Field(min_length=1)
    steps: list[ScriptedStep]


class ExecutedTool(BaseModel):
    """A tool call the application already ran or denied during the turn."""

    model_config = ConfigDict(frozen=True)

    name: str
    status: str
    error_code: str | None = None
    summary: str
    body: dict[str, Any] | None = None
    risk_level: str
    arguments_hash: str


class AgentResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    assistant_message: str = Field(min_length=1)
    proposed_tool_calls: list[ProposedToolCall]
    trace_id: UUID
    stop_reason: StopReason
    usage: Usage
    trace: AgentTrace
    executed_tools: list[ExecutedTool] = Field(default_factory=list)
    tools_handled: bool = False
    citations: list[Citation] = Field(default_factory=list)
    grounded_answer_failures: int = Field(default=0, ge=0)


class ModelMessage(BaseModel):
    """One message passed to a model adapter. Tool messages carry a safe JSON summary."""

    model_config = ConfigDict(frozen=True)

    role: ModelMessageRole
    content: str
    tool_name: str | None = None
    tool_call_id: str | None = None


class ToolSchema(BaseModel):
    """Allowlisted tool description advertised to the model."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=400)
    input_schema: dict[str, Any]


class ToolUseRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)


class AdapterUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class ModelText(BaseModel):
    kind: Literal["text"] = "text"
    text: str
    usage: AdapterUsage
    provider: str
    model_id: str
    latency_ms: int = Field(default=0, ge=0)


class ModelToolUse(BaseModel):
    kind: Literal["tool_use"] = "tool_use"
    requests: list[ToolUseRequest]
    usage: AdapterUsage
    provider: str
    model_id: str
    latency_ms: int = Field(default=0, ge=0)


class ModelProviderError(BaseModel):
    kind: Literal["error"] = "error"
    code: ProviderErrorCode
    usage: AdapterUsage = Field(default_factory=AdapterUsage)
    provider: str
    model_id: str
    latency_ms: int = Field(default=0, ge=0)


ModelResponse = ModelText | ModelToolUse | ModelProviderError


class ModelAdapter(Protocol):
    """One model call. The application executes tools; the adapter only proposes."""

    def complete(
        self,
        messages: list[ModelMessage],
        tools: list[ToolSchema],
        max_output_tokens: int,
    ) -> ModelResponse:
        """Return assistant text, tool-use requests, or a typed provider error."""


class AgentRunner(Protocol):
    """Port the API calls for one turn. Implementations must not require a cloud SDK."""

    def run(self, turn_context: TurnContext) -> AgentResult:
        """Run one turn and return the public result."""
