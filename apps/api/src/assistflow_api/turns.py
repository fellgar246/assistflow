"""Run one customer turn, execute allowlisted reads, and store the reply."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from assistflow_contracts.agent import (
    AgentResult,
    ExecutedTool,
    HistoryMessage,
    PromptRef,
    ToolSchema,
    TurnContext,
)
from assistflow_contracts.conversation import MessageRole, ToolActivity, ToolActivityStatus
from assistflow_conversations.commands import (
    ActorContext,
    append_message,
    record_agent_trace,
    record_tool_execution,
)
from assistflow_conversations.repository import (
    AgentTraceRecord,
    AgentTraceStepRecord,
    MessageRepository,
    ToolExecutionRecord,
    ToolExecutionRepository,
)
from sqlalchemy.orm import Session

from assistflow_api.agents import LoopRunner
from assistflow_knowledge.embeddings import DeterministicEmbedding
from assistflow_knowledge.retriever import KnowledgeRetriever
from assistflow_runtime import (
    DEFAULT_PROMPT_ID,
    DEFAULT_PROMPT_VERSION,
    bound_history,
)
from assistflow_tools import (
    ToolContext,
    ToolOutcome,
    ToolRegistry,
    build_registry,
    service_handlers,
)


def complete_agent_turn(
    session: Session,
    tenant_id: UUID,
    customer_id: UUID,
    conversation_id: UUID,
    customer_message_id: UUID,
    customer_message: str,
    idempotency_key: str,
    actor: ActorContext,
    runner: LoopRunner,
    *,
    max_tool_calls: int = 5,
    max_chunks: int = 4,
    score_floor: float = 0.28,
) -> AgentResult:
    """Ask the runner for a reply, run tier-0 tools, and persist the answer."""
    history = _history(session, tenant_id, conversation_id, customer_message_id)
    registry = build_registry(
        service_handlers(
            session,
            retriever=KnowledgeRetriever(
                session,
                DeterministicEmbedding(),
                chunk_cap=max_chunks,
                score_floor=score_floor,
            ),
        )
    )
    bound = runner.bind(
        _RegistryGateway(
            registry,
            ToolContext(
                tenant_id=tenant_id,
                customer_id=customer_id,
                actor_type=actor.actor_type,
                correlation_id=actor.correlation_id,
                conversation_id=conversation_id,
            ),
            max_tool_calls,
        )
    )
    result = bound.run(
        TurnContext(
            tenant_id=tenant_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            correlation_id=actor.correlation_id,
            customer_message=customer_message,
            history=history,
            prompt=PromptRef(id=DEFAULT_PROMPT_ID, version=DEFAULT_PROMPT_VERSION),
        )
    )
    executions = _store_handled(
        session,
        tenant_id,
        customer_id,
        conversation_id,
        actor,
        result,
    )
    assistant_text = result.assistant_message
    written = append_message(
        session,
        tenant_id,
        customer_id,
        conversation_id,
        MessageRole.ASSISTANT,
        assistant_text,
        f"agent-reply:{idempotency_key}",
        actor,
        citations=result.citations,
    )
    if executions:
        ToolExecutionRepository(session).attach_message(
            tenant_id,
            [record.id for record in executions],
            written.message.id,
        )
    created_at = datetime.now(UTC)
    record_agent_trace(
        session,
        AgentTraceRecord(
            id=result.trace_id,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            customer_id=customer_id,
            correlation_id=actor.correlation_id,
            prompt_id=result.trace.prompt_id,
            prompt_version=result.trace.prompt_version,
            stop_reason=result.stop_reason.value,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            provider=result.trace.provider,
            model_id=result.trace.model_id,
            grounded_answer_failures=result.grounded_answer_failures,
            created_at=created_at,
            steps=tuple(
                AgentTraceStepRecord(
                    id=uuid4(),
                    step_index=step.index,
                    kind=step.kind.value,
                    latency_ms=step.latency_ms,
                    input_summary=step.input_summary,
                )
                for step in result.trace.steps
            ),
        ),
        actor,
    )
    return result


def tool_activity_for(
    session: Session, tenant_id: UUID, conversation_id: UUID
) -> dict[UUID, list[ToolActivity]]:
    """Map an assistant message to the tool calls that produced it."""
    grouped: dict[UUID, list[ToolActivity]] = {}
    records = ToolExecutionRepository(session).list_for_conversation(tenant_id, conversation_id)
    for record in records:
        if record.assistant_message_id is None:
            continue
        grouped.setdefault(record.assistant_message_id, []).append(
            ToolActivity(
                tool_name=record.tool_name,
                status=ToolActivityStatus(record.status),
                reason=None if record.status == "succeeded" else record.result_summary,
            )
        )
    return grouped


def _store_handled(
    session: Session,
    tenant_id: UUID,
    customer_id: UUID,
    conversation_id: UUID,
    actor: ActorContext,
    result: AgentResult,
) -> list[ToolExecutionRecord]:
    stored: list[ToolExecutionRecord] = []
    for index, outcome in enumerate(result.executed_tools):
        stored.append(
            _store_outcome(
                session,
                tenant_id,
                customer_id,
                conversation_id,
                actor,
                outcome,
                index,
            )
        )
    return stored


class _RegistryGateway:
    """Advertise allowlisted schemas and run only tier-0 tools."""

    def __init__(self, registry: ToolRegistry, context: ToolContext, max_executions: int) -> None:
        self._registry = registry
        self._context = context
        self._max_executions = max_executions
        self._used = 0

    def schemas(self) -> list[ToolSchema]:
        advertised: list[ToolSchema] = []
        for tool in self._registry.advertised():
            description = (tool.argument_model.__doc__ or tool.name).strip().splitlines()[0]
            advertised.append(
                ToolSchema(
                    name=tool.name,
                    description=description[:400],
                    input_schema=tool.json_schema(),
                )
            )
        return advertised

    def execute(self, name: str, arguments: dict[str, Any]) -> ExecutedTool:
        registered = self._registry.lookup(name)
        if registered is None or registered.risk_level.value != "tier0":
            return ExecutedTool(
                name=name,
                status="blocked",
                error_code="tool_denied",
                summary="That action is not available.",
                body=None,
                risk_level="tier3",
                arguments_hash="",
            )
        outcome = self._registry.execute(
            name,
            arguments,
            self._context,
            executions_used=self._used,
            max_executions=self._max_executions,
        )
        self._used += 1
        return _executed(outcome)


def _executed(outcome: ToolOutcome) -> ExecutedTool:
    return ExecutedTool(
        name=outcome.name,
        status=outcome.status.value,
        error_code=outcome.error_code,
        summary=outcome.summary,
        body=outcome.body,
        risk_level=outcome.risk_level.value,
        arguments_hash=outcome.arguments_hash,
    )


def _store_outcome(
    session: Session,
    tenant_id: UUID,
    customer_id: UUID,
    conversation_id: UUID,
    actor: ActorContext,
    outcome: ExecutedTool,
    index: int,
) -> ToolExecutionRecord:
    now = datetime.now(UTC)
    record = ToolExecutionRecord(
        id=uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        correlation_id=actor.correlation_id,
        assistant_message_id=None,
        tool_name=outcome.name,
        arguments_hash=outcome.arguments_hash or "0" * 64,
        status=outcome.status,
        risk_level=outcome.risk_level,
        approval_id=None,
        started_at=now,
        finished_at=now,
        result_summary=outcome.summary[:240],
    )
    record_tool_execution(session, record, actor)
    append_message(
        session,
        tenant_id,
        customer_id,
        conversation_id,
        MessageRole.TOOL,
        outcome.summary,
        f"tool:{actor.correlation_id}:{index}:{outcome.name}",
        actor,
    )
    return record


def _history(
    session: Session,
    tenant_id: UUID,
    conversation_id: UUID,
    customer_message_id: UUID,
) -> list[HistoryMessage]:
    stored = MessageRepository(session).list_all(tenant_id, conversation_id)
    prior = [
        HistoryMessage(role=item.role, content=item.content)
        for item in stored
        if item.id != customer_message_id
    ]
    return bound_history(prior)
