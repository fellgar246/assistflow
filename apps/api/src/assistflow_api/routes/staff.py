"""Development staff console routes.

These routes exist only while execution is local. A later sign-in flow
replaces the staff header.
"""

from typing import Annotated, Any
from uuid import UUID

from assistflow_contracts.approval import ApprovalDecision, ApprovalView
from assistflow_contracts.conversation import (
    Citation,
    Message,
    MessageAuthor,
    MessagePage,
    MessageRole,
)
from assistflow_contracts.staff import (
    InboxQueue,
    StaffCommand,
    StaffConversation,
    StaffInboxPage,
    StaffMessageCreate,
    TicketDetail,
    TraceSummary,
)
from assistflow_contracts.support import Problem
from assistflow_conversations.approvals import ApprovalFailure, expire_elapsed, reject_approval
from assistflow_conversations.commands import ActorContext
from assistflow_conversations.repository import ConversationRepository, MessageRepository
from assistflow_customers.errors import SupportError
from assistflow_runtime.redaction import redact_text
from assistflow_tickets.handoff import post_human_reply, resolve_case, take_over
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from assistflow_api.actor import (
    LOCAL_STAFF,
    LocalStaffList,
    StaffActor,
    _parse_uuid,
    require_tenant_header,
)
from assistflow_api.approvals import confirm_stored_approval, present_approval
from assistflow_api.config import ExecutionMode, Settings
from assistflow_api.deps import PageQuery, correlation_id, get_session, page_query
from assistflow_api.staff_views import conversation_detail, inbox_page, ticket_detail, trace_summary
from assistflow_api.turns import tool_activity_for

router = APIRouter()

_ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": Problem},
    403: {"model": Problem},
    404: {"model": Problem},
    409: {"model": Problem},
    422: {"model": Problem},
}

Db = Annotated[Session, Depends(get_session)]
Page = Annotated[PageQuery, Depends(page_query)]
Correlation = Annotated[str, Depends(correlation_id)]


def require_staff_actor(
    request: Request,
    x_tenant_id: Annotated[str | None, Header()] = None,
    x_agent_id: Annotated[str | None, Header()] = None,
) -> StaffActor:
    """Resolve the local staff stub. Hidden once execution leaves local mode."""
    settings = request.app.state.settings
    if not isinstance(settings, Settings) or settings.execution_mode is not ExecutionMode.LOCAL:
        raise SupportError("not_found", "This resource was not found.", 404)
    tenant_id = require_tenant_header(x_tenant_id)
    agent_id = _parse_uuid(
        x_agent_id,
        "staff_required",
        "A development staff actor is required.",
        "invalid_staff",
        "The staff id is invalid.",
    )
    match = next(
        (item for item in LOCAL_STAFF if item.tenant_id == tenant_id and item.agent_id == agent_id),
        None,
    )
    if match is None:
        raise SupportError("denied", "That staff actor is not available.", 403)
    return StaffActor(
        tenant_id=match.tenant_id,
        agent_id=match.agent_id,
        display_name=match.label,
        actor_type="support_agent",
    )


Staff = Annotated[StaffActor, Depends(require_staff_actor)]


def _names(tenant_id: UUID) -> dict[UUID, str]:
    return {item.agent_id: item.label for item in LOCAL_STAFF if item.tenant_id == tenant_id}


def _context(actor: StaffActor, correlation: str) -> ActorContext:
    return ActorContext(
        actor_type=actor.actor_type,
        actor_id=actor.agent_id,
        correlation_id=correlation,
    )


def _stamp(response: Response, correlation: str) -> None:
    response.headers["X-Correlation-Id"] = correlation


@router.get("/dev/staff", response_model=LocalStaffList, responses=_ERRORS)
def list_local_staff(request: Request) -> LocalStaffList:
    """Seeded staff for local development. Hidden once a real session exists."""
    settings = request.app.state.settings
    if not isinstance(settings, Settings) or settings.execution_mode is not ExecutionMode.LOCAL:
        raise SupportError("not_found", "This resource was not found.", 404)
    return LocalStaffList(actors=list(LOCAL_STAFF))


@router.get("/staff/inbox", response_model=StaffInboxPage, responses=_ERRORS)
def read_inbox(
    response: Response,
    actor: Staff,
    session: Db,
    page: Page,
    correlation: Correlation,
    queue: Annotated[InboxQueue, Query()] = InboxQueue.ALL,
) -> StaffInboxPage:
    _stamp(response, correlation)
    return inbox_page(
        session,
        actor.tenant_id,
        queue,
        cursor=page.cursor,
        limit=page.limit,
        names=_names(actor.tenant_id),
    )


@router.get(
    "/staff/conversations/{conversation_id}",
    response_model=StaffConversation,
    responses=_ERRORS,
)
def read_staff_conversation(
    conversation_id: UUID,
    response: Response,
    actor: Staff,
    session: Db,
    correlation: Correlation,
) -> StaffConversation:
    _stamp(response, correlation)
    return conversation_detail(
        session,
        actor.tenant_id,
        conversation_id,
        _names(actor.tenant_id),
    )


@router.get(
    "/staff/conversations/{conversation_id}/messages",
    response_model=MessagePage,
    responses=_ERRORS,
)
def read_staff_transcript(
    conversation_id: UUID,
    response: Response,
    actor: Staff,
    session: Db,
    page: Page,
    correlation: Correlation,
) -> MessagePage:
    ConversationRepository(session).require(actor.tenant_id, conversation_id)
    listed = MessageRepository(session).list_page(
        actor.tenant_id,
        conversation_id,
        cursor=page.cursor,
        limit=page.limit,
    )
    activity = tool_activity_for(session, actor.tenant_id, conversation_id)
    approvals = _approvals_by_message(
        session,
        actor.tenant_id,
        conversation_id,
        _context(actor, correlation),
    )
    _stamp(response, correlation)
    visible = [item for item in listed.items if item.role is not MessageRole.TOOL]
    return MessagePage(
        items=[
            Message(
                id=item.id,
                role=item.role,
                content=item.content,
                created_at=item.created_at,
                tool_activity=activity.get(item.id, []),
                approvals=approvals.get(item.id, []),
                citations=[
                    Citation(title=title, version=version) for title, version in item.citations
                ],
                author_type=MessageAuthor(item.author_type),
                author_name=item.author_name,
            )
            for item in visible
        ],
        next_cursor=listed.next_cursor,
    )


@router.get(
    "/staff/conversations/{conversation_id}/trace",
    response_model=TraceSummary,
    responses=_ERRORS,
)
def read_trace(
    conversation_id: UUID,
    request: Request,
    response: Response,
    actor: Staff,
    session: Db,
    correlation: Correlation,
) -> TraceSummary:
    settings = request.app.state.settings
    step_limit = settings.max_agent_steps if isinstance(settings, Settings) else 8
    tool_limit = settings.max_tool_calls_per_turn if isinstance(settings, Settings) else 5
    _stamp(response, correlation)
    return trace_summary(
        session,
        actor.tenant_id,
        conversation_id,
        step_limit=step_limit,
        tool_limit=tool_limit,
    )


@router.post(
    "/staff/conversations/{conversation_id}/takeover",
    response_model=StaffConversation,
    responses=_ERRORS,
)
def post_takeover(
    conversation_id: UUID,
    body: StaffCommand,
    response: Response,
    actor: Staff,
    session: Db,
    correlation: Correlation,
) -> StaffConversation:
    take_over(
        session,
        actor.tenant_id,
        conversation_id,
        actor.agent_id,
        actor.display_name,
        body.idempotency_key,
        _context(actor, correlation),
    )
    _stamp(response, correlation)
    return conversation_detail(
        session,
        actor.tenant_id,
        conversation_id,
        _names(actor.tenant_id),
    )


@router.post(
    "/staff/conversations/{conversation_id}/messages",
    response_model=Message,
    status_code=201,
    responses=_ERRORS,
)
def post_staff_message(
    conversation_id: UUID,
    body: StaffMessageCreate,
    response: Response,
    actor: Staff,
    session: Db,
    correlation: Correlation,
) -> Message:
    written = post_human_reply(
        session,
        actor.tenant_id,
        conversation_id,
        actor.agent_id,
        actor.display_name,
        redact_text(body.content),
        body.idempotency_key,
        _context(actor, correlation),
    )
    if written.replayed:
        response.status_code = 200
    _stamp(response, correlation)
    return written.message


@router.post(
    "/staff/conversations/{conversation_id}/resolve",
    response_model=StaffConversation,
    responses=_ERRORS,
)
def post_resolve(
    conversation_id: UUID,
    body: StaffCommand,
    response: Response,
    actor: Staff,
    session: Db,
    correlation: Correlation,
) -> StaffConversation:
    resolve_case(
        session,
        actor.tenant_id,
        conversation_id,
        actor.agent_id,
        body.idempotency_key,
        _context(actor, correlation),
    )
    _stamp(response, correlation)
    return conversation_detail(
        session,
        actor.tenant_id,
        conversation_id,
        _names(actor.tenant_id),
    )


@router.get("/staff/tickets/{ticket_id}", response_model=TicketDetail, responses=_ERRORS)
def read_staff_ticket(
    ticket_id: UUID,
    response: Response,
    actor: Staff,
    session: Db,
    correlation: Correlation,
) -> TicketDetail:
    _stamp(response, correlation)
    return ticket_detail(session, actor.tenant_id, ticket_id, _names(actor.tenant_id))


@router.post(
    "/staff/conversations/{conversation_id}/approvals/{approval_id}/confirm",
    response_model=ApprovalView,
    responses=_ERRORS,
)
def confirm_as_staff(
    conversation_id: UUID,
    approval_id: UUID,
    body: ApprovalDecision,
    response: Response,
    actor: Staff,
    session: Db,
    correlation: Correlation,
) -> ApprovalView | JSONResponse:
    """Confirm with the same stored arguments. The staff id is recorded as approved_by."""
    del body
    customer_id = (
        ConversationRepository(session).require(actor.tenant_id, conversation_id).customer_id
    )
    result = confirm_stored_approval(
        session,
        actor.tenant_id,
        customer_id,
        conversation_id,
        approval_id,
        _context(actor, correlation),
    )
    _stamp(response, correlation)
    if isinstance(result, ApprovalFailure):
        return _failure(result, correlation)
    return result


@router.post(
    "/staff/conversations/{conversation_id}/approvals/{approval_id}/reject",
    response_model=ApprovalView,
    responses=_ERRORS,
)
def reject_as_staff(
    conversation_id: UUID,
    approval_id: UUID,
    body: ApprovalDecision,
    response: Response,
    actor: Staff,
    session: Db,
    correlation: Correlation,
) -> ApprovalView | JSONResponse:
    del body
    customer_id = (
        ConversationRepository(session).require(actor.tenant_id, conversation_id).customer_id
    )
    result = reject_approval(
        session,
        actor.tenant_id,
        customer_id,
        conversation_id,
        approval_id,
        _context(actor, correlation),
    )
    _stamp(response, correlation)
    if isinstance(result, ApprovalFailure):
        return _failure(result, correlation)
    return present_approval(result)


def _approvals_by_message(
    session: Session,
    tenant_id: UUID,
    conversation_id: UUID,
    actor: ActorContext,
) -> dict[UUID, list[ApprovalView]]:
    grouped: dict[UUID, list[ApprovalView]] = {}
    for record in expire_elapsed(session, tenant_id, conversation_id, actor):
        if record.assistant_message_id is None:
            continue
        grouped.setdefault(record.assistant_message_id, []).append(present_approval(record))
    return grouped


def _failure(result: ApprovalFailure, correlation: str) -> JSONResponse:
    denied = JSONResponse(
        status_code=result.status_code,
        content={"code": result.code, "message": result.message},
    )
    denied.headers["X-Correlation-Id"] = correlation
    return denied
