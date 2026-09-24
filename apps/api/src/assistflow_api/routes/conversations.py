"""Store and read support conversations.

When the assistant is enabled, a customer message also stores an in-process
reply and a trace. This module does not import a hosted model SDK.
"""

from typing import Annotated, Any
from uuid import UUID

from assistflow_contracts.conversation import (
    Conversation,
    ConversationPage,
    ConversationStatus,
    CustomerMessageCreate,
    Message,
    MessagePage,
    OpenConversation,
)
from assistflow_contracts.support import Problem
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
from sqlalchemy.orm import Session

from assistflow_api.actor import LOCAL_ACTORS, Actor, LocalActorList, require_actor
from assistflow_api.agents import build_agent_runner
from assistflow_api.config import ExecutionMode, Settings
from assistflow_api.deps import PageQuery, correlation_id, get_session, page_query
from assistflow_api.turns import complete_agent_turn

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
    result = append_customer_message(
        session,
        actor.tenant_id,
        actor.customer_id,
        conversation_id,
        body.content,
        body.idempotency_key,
        _context(actor, correlation),
        acknowledge=not assistant_enabled,
    )
    if assistant_enabled and not result.replayed:
        runner = build_agent_runner(settings)
        if runner is not None:
            complete_agent_turn(
                session,
                actor.tenant_id,
                actor.customer_id,
                conversation_id,
                result.message.id,
                body.content,
                body.idempotency_key,
                _context(actor, correlation),
                runner,
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
    _stamp(response, correlation)
    return MessagePage(
        items=[
            Message(id=item.id, role=item.role, content=item.content, created_at=item.created_at)
            for item in listed.items
        ],
        next_cursor=listed.next_cursor,
    )


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
