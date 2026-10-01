"""Store and read support conversations.

When the assistant is enabled, a customer message also stores a reply and a trace.
The hosted runtime client is constructed only when that flag is on.
"""

from typing import Annotated, Any
from uuid import UUID

from assistflow_contracts.approval import ApprovalDecision, ApprovalView
from assistflow_contracts.conversation import (
    Citation,
    Conversation,
    ConversationPage,
    ConversationStatus,
    CustomerMessageCreate,
    Message,
    MessagePage,
    MessageRole,
    OpenConversation,
)
from assistflow_contracts.support import Problem
from assistflow_conversations.approvals import ApprovalFailure, expire_elapsed, reject_approval
from assistflow_conversations.commands import (
    ActorContext,
    append_customer_message,
    open_conversation,
)
from assistflow_conversations.repository import (
    ConversationRecord,
    ConversationRepository,
    MessageRepository,
)
from assistflow_customers.errors import SupportError
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from assistflow_api.actor import LOCAL_ACTORS, Actor, LocalActorList, require_actor
from assistflow_api.agents import build_agent_runner
from assistflow_api.approvals import confirm_stored_approval, present_approval
from assistflow_api.config import ExecutionMode, Settings
from assistflow_api.deps import PageQuery, correlation_id, get_session, page_query
from assistflow_api.turns import complete_agent_turn, tool_activity_for
from assistflow_runtime.redaction import redact_text

router = APIRouter()

_ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": Problem},
    404: {"model": Problem},
    409: {"model": Problem},
    422: {"model": Problem},
}

DevActor = Annotated[Actor, Depends(require_actor)]
Db = Annotated[Session, Depends(get_session)]
Page = Annotated[PageQuery, Depends(page_query)]
Correlation = Annotated[str, Depends(correlation_id)]


def _stamp(response: Response, correlation: str) -> None:
    response.headers["X-Correlation-Id"] = correlation


def _context(actor: Actor, correlation: str) -> ActorContext:
    return ActorContext(
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        correlation_id=correlation,
    )


def _conversation(record: ConversationRecord, preview: str | None = None) -> Conversation:
    return Conversation(
        id=record.id,
        customer_id=record.customer_id,
        channel=record.channel,
        status=record.status,
        created_at=record.created_at,
        updated_at=record.updated_at,
        preview=preview,
    )


@router.get("/dev/actors", response_model=LocalActorList, responses=_ERRORS)
def list_local_actors(request: Request) -> LocalActorList:
    """Seeded customers for local development. Hidden once a real session exists."""
    settings = request.app.state.settings
    if not isinstance(settings, Settings) or settings.execution_mode is not ExecutionMode.LOCAL:
        raise SupportError("not_found", "This resource was not found.", 404)
    return LocalActorList(actors=list(LOCAL_ACTORS))


@router.post("/conversations", response_model=Conversation, status_code=201, responses=_ERRORS)
def post_conversation(
    body: OpenConversation,
    response: Response,
    actor: DevActor,
    session: Db,
    correlation: Correlation,
) -> Conversation:
    result = open_conversation(
        session,
        actor.tenant_id,
        actor.customer_id,
        body.idempotency_key,
        _context(actor, correlation),
    )
    if result.replayed:
        response.status_code = 200
    _stamp(response, correlation)
    return result.conversation


@router.get("/conversations", response_model=ConversationPage, responses=_ERRORS)
def list_conversations(
    response: Response,
    actor: DevActor,
    session: Db,
    page: Page,
    correlation: Correlation,
) -> ConversationPage:
    repository = ConversationRepository(session)
    listed = repository.list_for_customer(
        actor.tenant_id,
        actor.customer_id,
        cursor=page.cursor,
        limit=page.limit,
    )
    previews = MessageRepository(session).first_customer_contents(
        actor.tenant_id,
        [item.id for item in listed.items],
    )
    _stamp(response, correlation)
    return ConversationPage(
        items=[_conversation(item, previews.get(item.id)) for item in listed.items],
        next_cursor=listed.next_cursor,
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=Conversation,
    responses=_ERRORS,
)
def read_conversation(
    conversation_id: UUID,
    response: Response,
    actor: DevActor,
    session: Db,
    correlation: Correlation,
) -> Conversation:
    record = ConversationRepository(session).require_for_customer(
        actor.tenant_id, actor.customer_id, conversation_id
    )
    preview = (
        MessageRepository(session)
        .first_customer_contents(actor.tenant_id, [conversation_id])
        .get(conversation_id)
    )
    _stamp(response, correlation)
    return _conversation(record, preview)


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=Message,
    status_code=201,
    responses=_ERRORS,
)
def post_customer_message(
    conversation_id: UUID,
    body: CustomerMessageCreate,
    request: Request,
    response: Response,
    actor: DevActor,
    session: Db,
    correlation: Correlation,
) -> Message:
    settings = request.app.state.settings
    assistant_enabled = isinstance(settings, Settings) and settings.ai_enabled
    content = redact_text(body.content)
    result = append_customer_message(
        session,
        actor.tenant_id,
        actor.customer_id,
        conversation_id,
        content,
        body.idempotency_key,
        _context(actor, correlation),
        acknowledge=not assistant_enabled,
    )
    if assistant_enabled and not result.replayed:
        runner = build_agent_runner(
            settings,
            quota=getattr(request.app.state, "session_quota", None),
            transport=getattr(request.app.state, "runtime_transport", None),
        )
        if runner is not None:
            complete_agent_turn(
                session,
                actor.tenant_id,
                actor.customer_id,
                conversation_id,
                result.message.id,
                content,
                body.idempotency_key,
                _context(actor, correlation),
                runner,
                max_tool_calls=settings.max_tool_calls_per_turn,
                max_chunks=settings.max_chunks_per_retrieval,
                score_floor=settings.retrieval_score_floor,
                settings=settings,
            )
    if result.replayed:
        response.status_code = 200
    _stamp(response, correlation)
    return result.message


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=MessagePage,
    responses=_ERRORS,
)
def read_transcript(
    conversation_id: UUID,
    response: Response,
    actor: DevActor,
    session: Db,
    page: Page,
    correlation: Correlation,
) -> MessagePage:
    ConversationRepository(session).require_for_customer(
        actor.tenant_id, actor.customer_id, conversation_id
    )
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
        actor.customer_id,
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
            )
            for item in visible
        ],
        next_cursor=listed.next_cursor,
    )


@router.post(
    "/conversations/{conversation_id}/approvals/{approval_id}/confirm",
    response_model=ApprovalView,
    responses=_ERRORS,
)
def confirm_approval(
    conversation_id: UUID,
    approval_id: UUID,
    body: ApprovalDecision,
    response: Response,
    actor: DevActor,
    session: Db,
    correlation: Correlation,
) -> ApprovalView | JSONResponse:
    """Confirm one stored proposal. The body cannot carry a new address."""
    del body
    result = confirm_stored_approval(
        session,
        actor.tenant_id,
        actor.customer_id,
        conversation_id,
        approval_id,
        _context(actor, correlation),
    )
    _stamp(response, correlation)
    if isinstance(result, ApprovalFailure):
        return _failure(result, correlation)
    return result


@router.post(
    "/conversations/{conversation_id}/approvals/{approval_id}/reject",
    response_model=ApprovalView,
    responses=_ERRORS,
)
def reject_customer_approval(
    conversation_id: UUID,
    approval_id: UUID,
    body: ApprovalDecision,
    response: Response,
    actor: DevActor,
    session: Db,
    correlation: Correlation,
) -> ApprovalView | JSONResponse:
    """Cancel one stored proposal. Business rows stay unchanged."""
    del body
    result = reject_approval(
        session,
        actor.tenant_id,
        actor.customer_id,
        conversation_id,
        approval_id,
        _context(actor, correlation),
    )
    _stamp(response, correlation)
    if isinstance(result, ApprovalFailure):
        return _failure(result, correlation)
    return present_approval(result)


def _failure(result: ApprovalFailure, correlation: str) -> JSONResponse:
    denied = JSONResponse(
        status_code=result.status_code,
        content={"code": result.code, "message": result.message},
    )
    denied.headers["X-Correlation-Id"] = correlation
    return denied


def _approvals_by_message(
    session: Session,
    tenant_id: UUID,
    customer_id: UUID,
    conversation_id: UUID,
    actor: ActorContext,
) -> dict[UUID, list[ApprovalView]]:
    ConversationRepository(session).require_for_customer(tenant_id, customer_id, conversation_id)
    grouped: dict[UUID, list[ApprovalView]] = {}
    for record in expire_elapsed(session, tenant_id, conversation_id, actor):
        if record.assistant_message_id is None:
            continue
        grouped.setdefault(record.assistant_message_id, []).append(present_approval(record))
    return grouped


def require_open_conversation(
    session: Session, tenant_id: UUID, customer_id: UUID, conversation_id: UUID
) -> None:
    """A ticket may attach only to an open conversation in the same tenant and customer."""
    found = ConversationRepository(session).get(tenant_id, conversation_id)
    if found is None or found.customer_id != customer_id:
        raise SupportError(
            "conversation_not_found",
            f"Conversation {conversation_id} was not found.",
            404,
        )
    if found.status is not ConversationStatus.OPEN:
        raise SupportError(
            "invalid_conversation_status",
            "A ticket can be opened only for an open conversation.",
            409,
        )
