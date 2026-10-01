"""Run one customer turn, execute allowlisted reads, and store the reply."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog
from assistflow_contracts.agent import (
    AgentResult,
    ExecutedTool,
    HistoryMessage,
    PromptRef,
    TurnContext,
)
from assistflow_contracts.conversation import (
    Citation,
    MessageRole,
    ToolActivity,
    ToolActivityStatus,
)
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

from assistflow_api.agents import TurnRunner
from assistflow_api.config import Settings
from assistflow_api.retrieval import build_knowledge_retriever
from assistflow_knowledge.embeddings import DeterministicEmbedding
from assistflow_knowledge.retriever import KnowledgeRetriever, LocalKnowledgeRetriever
from assistflow_runtime import (
    DEFAULT_PROMPT_ID,
    DEFAULT_PROMPT_VERSION,
    bound_history,
)
from assistflow_runtime.redaction import REDACTED, redact_text
from assistflow_tools import (
    LocalToolGateway,
    build_registry,
    service_handlers,
)
from assistflow_tools.writes import approved_write_handlers

logger = structlog.get_logger("assistflow.turn")


def complete_agent_turn(
    session: Session,
    tenant_id: UUID,
    customer_id: UUID,
    conversation_id: UUID,
    customer_message_id: UUID,
    customer_message: str,
    idempotency_key: str,
    actor: ActorContext,
    runner: TurnRunner,
    *,
    max_tool_calls: int = 5,
    max_chunks: int = 4,
    score_floor: float = 0.28,
    settings: Settings | None = None,
    retriever: KnowledgeRetriever | None = None,
) -> AgentResult:
    """Ask the runner for a reply, run tier-0 tools, and persist the answer."""
    history = _history(session, tenant_id, conversation_id, customer_message_id)
    bound = runner.bind(
        build_turn_gateway(
            session,
            max_tool_calls=max_tool_calls,
            max_chunks=max_chunks,
            score_floor=score_floor,
            settings=settings,
            retriever=retriever,
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
            actor_type=actor.actor_type,
        )
    )
    logger.info(
        "turn_persisted",
        assistant_message=result.assistant_message,
        tool_summaries=[item.summary for item in result.executed_tools],
        trace_summaries=[step.input_summary for step in result.trace.steps],
    )
    result = _redacted_result(result)
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
            runtime_invocation_id=result.trace.runtime_invocation_id,
            duration_ms=result.trace.duration_ms,
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


def build_turn_gateway(
    session: Session,
    *,
    max_tool_calls: int,
    max_chunks: int,
    score_floor: float,
    settings: Settings | None = None,
    retriever: KnowledgeRetriever | None = None,
) -> LocalToolGateway:
    """Bind the local gateway. Tier 1 writes are on. Tier 2 mutation stays behind approval."""
    if retriever is None:
        retriever = (
            build_knowledge_retriever(settings, session)
            if settings is not None
            else LocalKnowledgeRetriever(
                session,
                DeterministicEmbedding(),
                chunk_cap=max_chunks,
                score_floor=score_floor,
            )
        )
    handlers = service_handlers(session, retriever=retriever)
    registry = build_registry(handlers, approved=approved_write_handlers(session))
    return LocalToolGateway(registry, max_executions=max_tool_calls, writes_enabled=True)


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


def _redacted_result(result: AgentResult) -> AgentResult:
    """Copy a turn result with secret-shaped strings removed."""
    return result.model_copy(
        update={
            "assistant_message": _nonempty(redact_text(result.assistant_message)),
            "executed_tools": [
                item.model_copy(update={"summary": redact_text(item.summary)[:240]})
                for item in result.executed_tools
            ],
            "trace": result.trace.model_copy(
                update={
                    "steps": [
                        step.model_copy(
                            update={"input_summary": redact_text(step.input_summary)[:240]}
                        )
                        for step in result.trace.steps
                    ]
                }
            ),
            "citations": [
                Citation(title=_citation_title(item.title), version=item.version)
                for item in result.citations
            ],
        }
    )


def _nonempty(text: str) -> str:
    if text.strip() == "":
        return REDACTED
    return text


def _citation_title(title: str) -> str:
    cleaned = redact_text(title).strip() or "Document"
    return cleaned[:200]


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
