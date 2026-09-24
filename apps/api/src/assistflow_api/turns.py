"""Run one customer turn, execute allowlisted reads, and store the reply."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from assistflow_contracts.agent import (
    AgentResult,
    AgentRunner,
    HistoryMessage,
    PromptRef,
    ProposedToolCall,
    StopReason,
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
from assistflow_test_fixtures.agent_scripts import follow_up_calls, reply_from_tools
from sqlalchemy.orm import Session

from assistflow_runtime import (
    DEFAULT_PROMPT_ID,
    DEFAULT_PROMPT_VERSION,
    bound_history,
)
from assistflow_tools import ToolContext, ToolOutcome, build_registry, service_handlers


def complete_agent_turn(
    session: Session,
    tenant_id: UUID,
    customer_id: UUID,
    conversation_id: UUID,
    customer_message_id: UUID,
    customer_message: str,
    idempotency_key: str,
    actor: ActorContext,
    runner: AgentRunner,
    *,
    max_tool_calls: int = 5,
) -> AgentResult:
    """Ask the runner for a reply, run tier-0 tools, and persist the answer."""
    history = _history(session, tenant_id, conversation_id, customer_message_id)
    result = runner.run(
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
    executions = _execute_proposals(
        session,
        tenant_id,
        customer_id,
        conversation_id,
        customer_message,
        actor,
        result,
        max_tool_calls=max_tool_calls,
    )
    assistant_text = result.assistant_message
    if executions:
        assistant_text = reply_from_tools([_view(outcome) for _record, outcome in executions])
    written = append_message(
        session,
        tenant_id,
        customer_id,
        conversation_id,
        MessageRole.ASSISTANT,
        assistant_text,
        f"agent-reply:{idempotency_key}",
        actor,
    )
    if executions:
        ToolExecutionRepository(session).attach_message(
            tenant_id,
            [record.id for record, _outcome in executions],
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


def _execute_proposals(
    session: Session,
    tenant_id: UUID,
    customer_id: UUID,
    conversation_id: UUID,
    customer_message: str,
    actor: ActorContext,
    result: AgentResult,
    *,
    max_tool_calls: int,
) -> list[tuple[ToolExecutionRecord, ToolOutcome]]:
    if result.stop_reason is not StopReason.COMPLETED:
        return []
    registry = build_registry(service_handlers(session))
    context = ToolContext(
        tenant_id=tenant_id,
        customer_id=customer_id,
        actor_type=actor.actor_type,
        correlation_id=actor.correlation_id,
        conversation_id=conversation_id,
    )
    pending = list(result.proposed_tool_calls)
    stored: list[tuple[ToolExecutionRecord, ToolOutcome]] = []
    seen: set[tuple[str, str]] = set()
    while pending and len(stored) < max_tool_calls:
        call = pending.pop(0)
        key = (call.name, _stable_arguments(call))
        if key in seen:
            continue
        seen.add(key)
        outcome = registry.execute(
            call.name,
            dict(call.arguments),
            context,
            executions_used=len(stored),
            max_executions=max_tool_calls,
        )
        record = _store_outcome(
            session,
            tenant_id,
            customer_id,
            conversation_id,
            actor,
            outcome,
            len(stored),
        )
        stored.append((record, outcome))
        if len(stored) >= max_tool_calls:
            break
        pending.extend(follow_up_calls(customer_message, [_view(item) for _record, item in stored]))
        pending = [item for item in pending if (item.name, _stable_arguments(item)) not in seen]
    return stored


def _store_outcome(
    session: Session,
    tenant_id: UUID,
    customer_id: UUID,
    conversation_id: UUID,
    actor: ActorContext,
    outcome: ToolOutcome,
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
        arguments_hash=outcome.arguments_hash,
        status=outcome.status.value,
        risk_level=outcome.risk_level.value,
        approval_id=None,
        started_at=now,
        finished_at=now,
        result_summary=outcome.summary,
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


def _view(outcome: ToolOutcome) -> dict[str, Any]:
    return {
        "name": outcome.name,
        "status": outcome.status.value,
        "error_code": outcome.error_code,
        "body": outcome.body,
    }


def _stable_arguments(call: ProposedToolCall) -> str:
    return str(sorted(call.arguments.items()))


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
