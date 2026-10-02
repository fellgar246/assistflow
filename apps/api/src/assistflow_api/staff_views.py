"""Staff read models. Pages are rendered from stored rows, not from a model call."""

from uuid import UUID

from assistflow_contracts.approval import ApprovalStatus
from assistflow_contracts.conversation import ConversationStatus
from assistflow_contracts.staff import (
    InboxCounts,
    InboxQueue,
    StaffConversation,
    StaffInboxPage,
    TicketDetail,
    TicketNoteView,
    TraceStepView,
    TraceSummary,
    TraceTurnView,
)
from assistflow_contracts.support import TicketPriority
from assistflow_conversations.repository import (
    AgentTraceRecord,
    AgentTraceRepository,
    AgentTraceStepRecord,
    ApprovalRepository,
    ConversationRecord,
    ConversationRepository,
    MessageRepository,
    ToolExecutionRecord,
    ToolExecutionRepository,
)
from assistflow_customers.repository import CustomerRepository
from assistflow_tickets.repository import TicketNoteRepository, TicketRecord, TicketRepository
from sqlalchemy.orm import Session

_WAITING = (ConversationStatus.ESCALATED, ConversationStatus.WAITING_APPROVAL)
_KIND = {
    "model": "Model call",
    "tool_proposal": "Tool call",
    "tool_denial": "Tool call",
    "guardrail": "Guardrail",
    "budget": "Limit",
}
_ERROR_TEXT = {
    "tool_denied": "This action is not available.",
    "not_found": "That record was not found.",
    "validation_error": "The request was not valid.",
    "timeout": "The check timed out.",
    "tool_limit": "This turn reached its tool limit.",
    "denied": "That action is not available.",
    "stopped_budget": "This turn reached its limit.",
}
_PRIORITY_RANK = {TicketPriority.HIGH: 3, TicketPriority.NORMAL: 2, TicketPriority.LOW: 1}


def inbox_page(
    session: Session,
    tenant_id: UUID,
    queue: InboxQueue,
    *,
    cursor: str | None,
    limit: int,
    names: dict[UUID, str],
) -> StaffInboxPage:
    repository = ConversationRepository(session)
    listed = repository.list_by_status(
        tenant_id,
        _statuses(queue),
        cursor=cursor,
        limit=limit,
    )
    return StaffInboxPage(
        items=[_conversation(session, tenant_id, item, names) for item in listed.items],
        next_cursor=listed.next_cursor,
        counts=InboxCounts(
            all=repository.count_status(tenant_id, ConversationStatus.ESCALATED)
            + repository.count_status(tenant_id, ConversationStatus.WAITING_APPROVAL),
            escalated=repository.count_status(tenant_id, ConversationStatus.ESCALATED),
            waiting_approval=repository.count_status(
                tenant_id, ConversationStatus.WAITING_APPROVAL
            ),
        ),
    )


def conversation_detail(
    session: Session,
    tenant_id: UUID,
    conversation_id: UUID,
    names: dict[UUID, str],
) -> StaffConversation:
    record = ConversationRepository(session).require(tenant_id, conversation_id)
    return _conversation(session, tenant_id, record, names)


def ticket_detail(
    session: Session,
    tenant_id: UUID,
    ticket_id: UUID,
    names: dict[UUID, str],
) -> TicketDetail:
    ticket = TicketRepository(session).require(tenant_id, ticket_id)
    customer = CustomerRepository(session).require(tenant_id, ticket.customer_id)
    notes = TicketNoteRepository(session).list_for_ticket(tenant_id, ticket.id)
    return TicketDetail(
        id=ticket.id,
        customer_display_name=customer.display_name,
        priority=ticket.priority,
        category=ticket.category,
        status=ticket.status,
        summary=ticket.summary,
        conversation_id=ticket.conversation_id,
        assigned_to=ticket.assigned_to,
        assignee_name=names.get(ticket.assigned_to) if ticket.assigned_to else None,
        created_at=ticket.created_at,
        notes=[
            TicketNoteView(
                id=note.id,
                body=note.body,
                author_type=note.author_type,
                created_at=note.created_at,
            )
            for note in notes
        ],
    )


def trace_summary(
    session: Session,
    tenant_id: UUID,
    conversation_id: UUID,
    *,
    step_limit: int,
    tool_limit: int,
) -> TraceSummary:
    ConversationRepository(session).require(tenant_id, conversation_id)
    traces = AgentTraceRepository(session).list_for_conversation(tenant_id, conversation_id)
    executions = ToolExecutionRepository(session).list_for_conversation(tenant_id, conversation_id)
    turns = [
        _turn(trace, executions, step_limit=step_limit, tool_limit=tool_limit) for trace in traces
    ]
    return TraceSummary(items=turns)


def _statuses(queue: InboxQueue) -> tuple[ConversationStatus, ...]:
    if queue is InboxQueue.ESCALATED:
        return (ConversationStatus.ESCALATED,)
    if queue is InboxQueue.WAITING_APPROVAL:
        return (ConversationStatus.WAITING_APPROVAL,)
    return _WAITING


def _conversation(
    session: Session,
    tenant_id: UUID,
    record: ConversationRecord,
    names: dict[UUID, str],
) -> StaffConversation:
    customer = CustomerRepository(session).require(tenant_id, record.customer_id)
    preview = (
        MessageRepository(session).latest_visible_contents(tenant_id, [record.id]).get(record.id)
    )
    tickets = TicketRepository(session).list_for_conversations(tenant_id, [record.id])
    ticket = _preferred_ticket(tickets)
    pending = sum(
        1
        for item in ApprovalRepository(session).list_for_conversation(tenant_id, record.id)
        if item.status is ApprovalStatus.PENDING
    )
    text = None if preview is None else preview.strip().replace("\n", " ")
    if text is not None and len(text) > 180:
        text = text[:180]
    return StaffConversation(
        id=record.id,
        customer_id=record.customer_id,
        customer_display_name=customer.display_name,
        channel=record.channel,
        status=record.status,
        assigned_to=record.assigned_to,
        assignee_name=names.get(record.assigned_to) if record.assigned_to else None,
        ticket_id=None if ticket is None else ticket.id,
        ticket_priority=None if ticket is None else ticket.priority,
        pending_approval_count=pending,
        preview=text,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _preferred_ticket(tickets: list[TicketRecord]) -> TicketRecord | None:
    if not tickets:
        return None
    return max(
        tickets,
        key=lambda item: (_PRIORITY_RANK.get(item.priority, 0), item.created_at, str(item.id)),
    )


def _turn(
    trace: AgentTraceRecord,
    executions: list[ToolExecutionRecord],
    *,
    step_limit: int,
    tool_limit: int,
) -> TraceTurnView:
    matched = [item for item in executions if item.correlation_id == trace.correlation_id]
    cursor = 0
    steps: list[TraceStepView] = []
    for step in trace.steps:
        view, cursor = _step(step, matched, cursor)
        steps.append(view)
    tool_calls = sum(1 for item in steps if item.kind == "Tool call")
    return TraceTurnView(
        id=trace.id,
        stop_reason=trace.stop_reason,
        created_at=trace.created_at,
        steps=steps,
        step_count=len(steps),
        step_limit=step_limit,
        tool_call_count=tool_calls,
        tool_call_limit=tool_limit,
        total_latency_ms=sum(item.latency_ms for item in steps),
        stopped_by_limit=trace.stop_reason == "stopped_budget",
    )


def _step(
    step: AgentTraceStepRecord,
    executions: list[ToolExecutionRecord],
    cursor: int,
) -> tuple[TraceStepView, int]:
    tool_name = _tool_name(step.input_summary)
    execution: ToolExecutionRecord | None = None
    if step.kind in {"tool_proposal", "tool_denial"}:
        execution, cursor = _match_execution(executions, cursor, tool_name)
    status = _status(step, execution)
    error_code = execution.error_code if execution is not None else None
    if error_code is None and step.kind == "tool_denial":
        error_code = "tool_denied"
    if error_code is None and step.kind == "budget":
        error_code = "stopped_budget"
    detail = _detail(step, execution, status, error_code)
    digest = None
    if execution is not None and execution.arguments_hash:
        digest = execution.arguments_hash[:8]
    name = execution.tool_name if execution is not None else tool_name
    return (
        TraceStepView(
            step=step.step_index + 1,
            kind=_KIND.get(step.kind, "Model call"),
            tool_name=name,
            status=status,
            latency_ms=step.latency_ms,
            error_code=error_code if status in {"failed", "blocked"} else None,
            detail=detail,
            arguments_hash=digest,
        ),
        cursor,
    )


def _match_execution(
    executions: list[ToolExecutionRecord],
    cursor: int,
    tool_name: str | None,
) -> tuple[ToolExecutionRecord | None, int]:
    for index in range(cursor, len(executions)):
        if tool_name is None or executions[index].tool_name == tool_name:
            return executions[index], index + 1
    return None, cursor


def _status(step: AgentTraceStepRecord, execution: ToolExecutionRecord | None) -> str | None:
    if execution is not None:
        return execution.status
    if step.kind == "tool_denial":
        return "blocked"
    if step.kind == "tool_proposal":
        return "proposed"
    if step.kind == "budget":
        return "blocked"
    if step.kind == "guardrail" and "block" in step.input_summary:
        return "blocked"
    if step.kind == "model":
        return "succeeded"
    return None


def _detail(
    step: AgentTraceStepRecord,
    execution: ToolExecutionRecord | None,
    status: str | None,
    error_code: str | None,
) -> str:
    summary = execution.result_summary if execution is not None else step.input_summary
    if status in {"failed", "blocked"}:
        if " " in summary:
            return summary
        if error_code is not None and error_code in _ERROR_TEXT:
            return _ERROR_TEXT[error_code]
    return summary


def _tool_name(summary: str) -> str | None:
    for prefix in ("proposed ", "denied "):
        if summary.startswith(prefix):
            name = summary[len(prefix) :].strip()
            return name or None
    return None
