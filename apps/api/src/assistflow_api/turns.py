"""Run one customer turn and store the assistant reply plus its trace."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from assistflow_contracts.agent import (
    AgentResult,
    AgentRunner,
    HistoryMessage,
    PromptRef,
    TurnContext,
)
from assistflow_contracts.conversation import MessageRole
from assistflow_conversations.commands import (
    ActorContext,
    append_message,
    record_agent_trace,
)
from assistflow_conversations.repository import (
    AgentTraceRecord,
    AgentTraceStepRecord,
    MessageRepository,
)
from sqlalchemy.orm import Session

from assistflow_runtime import (
    DEFAULT_PROMPT_ID,
    DEFAULT_PROMPT_VERSION,
    bound_history,
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
    runner: AgentRunner,
) -> AgentResult:
    """Ask the runner for a reply and persist that reply with its trace."""
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
    append_message(
        session,
        tenant_id,
        customer_id,
        conversation_id,
        MessageRole.ASSISTANT,
        result.assistant_message,
        f"agent-reply:{idempotency_key}",
        actor,
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
