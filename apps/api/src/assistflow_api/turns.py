"""Run one customer turn, execute allowlisted reads, and store the reply."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import structlog
from assistflow_contracts.agent import (
    AgentResult,
    ExecutedTool,
    HistoryMessage,
    PromptRef,
    StopReason,
    TurnContext,
)
from assistflow_contracts.conversation import (
    Citation,
    MessageRole,
    ToolActivity,
    ToolActivityStatus,
)
from assistflow_contracts.gateway import GatewayActor
from assistflow_contracts.memory import SessionFacts
from assistflow_contracts.observe import record_hop
from assistflow_conversations.approvals import store_proposal
from assistflow_conversations.commands import (
    ActorContext,
    append_message,
    record_agent_trace,
    record_tool_execution,
)
from assistflow_conversations.repository import (
    AgentTraceRecord,
    AgentTraceStepRecord,
    ApprovalRepository,
    MessageRepository,
    ToolExecutionRecord,
    ToolExecutionRepository,
)
from sqlalchemy.orm import Session

from assistflow_api.agents import TurnRunner
from assistflow_api.config import Settings
from assistflow_api.logging import payloads_suppressed
from assistflow_api.metrics import record_turn
from assistflow_api.retrieval import build_knowledge_retriever
from assistflow_knowledge.embeddings import DeterministicEmbedding
from assistflow_knowledge.retriever import KnowledgeRetriever, LocalKnowledgeRetriever
from assistflow_memory import (
    MEMORY_LIMIT_MESSAGE,
    MemoryLimitError,
    MemoryPorts,
    PreferenceRejected,
    build_memory_ports,
    preference_statements,
)
from assistflow_memory.facts import remember_tool_facts
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
    memory: MemoryPorts | None = None,
) -> AgentResult:
    """Ask the runner for a reply, run tier-0 tools, and persist the answer."""
    started = time.perf_counter()
    history = _history(session, tenant_id, conversation_id, customer_message_id)
    ports = memory_ports_for(settings, session, memory)
    now = datetime.now(UTC)
    _remember_preferences(ports, tenant_id, customer_id, customer_message, now)
    session_memory = _session_facts(ports, tenant_id, customer_id, conversation_id, now)
    preferences = (
        [] if ports.preferences is None else ports.preferences.load(tenant_id, customer_id, now)
    )
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
    tool_actor = gateway_actor_for(
        tenant_id=tenant_id,
        customer_id=customer_id,
        actor_type=actor.actor_type,
        correlation_id=actor.correlation_id,
        conversation_id=conversation_id,
    )
    result = bound.run(
        TurnContext(
            tenant_id=tool_actor.tenant_id,
            customer_id=tool_actor.customer_id,
            conversation_id=tool_actor.conversation_id,
            correlation_id=tool_actor.correlation_id,
            customer_message=customer_message,
            history=history,
            prompt=PromptRef(id=DEFAULT_PROMPT_ID, version=DEFAULT_PROMPT_VERSION),
            actor_type=tool_actor.actor_type,
            session_memory=session_memory,
            preferences=preferences,
        )
    )
    if ports.session is not None:
        try:
            remember_tool_facts(
                ports.session,
                tenant_id,
                customer_id,
                conversation_id,
                result.executed_tools,
                now,
            )
        except MemoryLimitError:
            result = result.model_copy(
                update={
                    "assistant_message": MEMORY_LIMIT_MESSAGE,
                    "stop_reason": StopReason.FAILED,
                    "trace": result.trace.model_copy(update={"stop_reason": StopReason.FAILED}),
                }
            )
    result = _redacted_result(result)
    _log_turn(result)
    executions, approval_ids = _store_handled(
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
    if approval_ids:
        ApprovalRepository(session).attach_message(
            tenant_id,
            approval_ids,
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
    latency_ms = _elapsed_ms(started)
    record_hop(
        "agent",
        correlation_id=actor.correlation_id,
        latency_ms=latency_ms,
        tenant_id=str(tenant_id),
        conversation_id=str(conversation_id),
        status=result.stop_reason.value,
        runtime_trace_id=result.trace.runtime_invocation_id,
    )
    record_turn(result, tenant_id, latency_ms)
    return result


def gateway_actor_for(
    *,
    tenant_id: UUID,
    customer_id: UUID,
    actor_type: str,
    correlation_id: str,
    conversation_id: UUID,
) -> GatewayActor:
    """Build the tool actor from the verified request. Model arguments cannot replace it."""
    return GatewayActor(
        tenant_id=tenant_id,
        customer_id=customer_id,
        actor_type=actor_type,
        correlation_id=correlation_id,
        conversation_id=conversation_id,
    )


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
) -> tuple[list[ToolExecutionRecord], list[UUID]]:
    stored: list[ToolExecutionRecord] = []
    approvals: list[UUID] = []
    for index, outcome in enumerate(result.executed_tools):
        proposal = _proposal_body(outcome)
        if proposal is not None:
            change, arguments = proposal
            saved = store_proposal(
                session,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                actor=actor,
                tool_name=outcome.name,
                arguments=arguments,
                proposed_change=change,
                summary=outcome.summary,
            )
            if saved.execution.assistant_message_id is None:
                stored.append(saved.execution)
            if saved.approval.assistant_message_id is None:
                approvals.append(saved.approval.id)
            if not saved.reused:
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
            continue
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
    return stored, approvals


def _proposal_body(outcome: ExecutedTool) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if outcome.status != "pending_approval" or not isinstance(outcome.body, dict):
        return None
    change = outcome.body.get("proposed_change")
    arguments = outcome.body.get("arguments")
    if not isinstance(change, dict) or not isinstance(arguments, dict):
        return None
    return change, arguments


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
        error_code=outcome.error_code,
        latency_ms=outcome.latency_ms,
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


def _log_turn(result: AgentResult) -> None:
    """Log names, codes, and timings. Raw model documents stay out of the line."""
    fields: dict[str, object] = {
        "stop_reason": result.stop_reason.value,
        "tool_names": [item.name for item in result.executed_tools],
        "error_codes": [item.error_code for item in result.executed_tools if item.error_code],
        "latency_ms": [item.latency_ms for item in result.executed_tools],
        "input_tokens": result.usage.input_tokens,
        "output_tokens": result.usage.output_tokens,
    }
    if not payloads_suppressed():
        fields["assistant_message"] = result.assistant_message
    logger.info("turn_persisted", **fields)


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))


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


def memory_ports_for(
    settings: Settings | None, session: Session, memory: MemoryPorts | None
) -> MemoryPorts:
    """Build adapters only when the caller did not already supply them."""
    if memory is not None:
        return memory
    if settings is None:
        return MemoryPorts()
    return build_memory_ports(
        short_term_enabled=settings.short_term_memory_enabled,
        long_term_enabled=settings.long_term_memory_enabled,
        agentcore_enabled=settings.agentcore_enabled,
        max_events=settings.max_memory_events_per_session,
        max_session_minutes=settings.max_session_minutes,
        session=session,
        region=settings.aws_region,
        memory_id=settings.agentcore_memory_id,
    )


def _remember_preferences(
    ports: MemoryPorts,
    tenant_id: UUID,
    customer_id: UUID,
    customer_message: str,
    now: datetime,
) -> None:
    if ports.preferences is None:
        return
    for key, value in preference_statements(customer_message):
        try:
            ports.preferences.remember(tenant_id, customer_id, key, value, now)
        except PreferenceRejected:
            continue


def _session_facts(
    ports: MemoryPorts,
    tenant_id: UUID,
    customer_id: UUID,
    conversation_id: UUID,
    now: datetime,
) -> SessionFacts | None:
    if ports.session is None:
        return None
    loaded = ports.session.load(tenant_id, customer_id, conversation_id, now)
    if loaded.last_order_id or loaded.last_shipment_status:
        return loaded
    return None


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
