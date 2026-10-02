"""Request dependencies for the verified caller and paging."""

from collections.abc import Iterator
from contextlib import nullcontext
from typing import Annotated, cast
from uuid import uuid4

import structlog
from assistflow_customers.errors import SupportError
from fastapi import Header, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from assistflow_api.actor import Actor, Role, StaffActor, display_name_for
from assistflow_api.auth import SESSION_COOKIE, TokenError, TokenVerifier, VerifiedToken
from assistflow_api.event_queue import InMemoryEventQueue
from assistflow_api.events import publish_outbox

logger = structlog.get_logger(__name__)


class PageQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    limit: int
    cursor: str | None


def require_customer(request: Request) -> Actor:
    """Return the customer from the verified token. Another role is forbidden."""
    verified = _verified(request)
    if verified.role is not Role.CUSTOMER or verified.customer_id is None:
        _deny(request, "forbidden")
        raise SupportError("forbidden", "That action is not available.", 403)
    return Actor(
        tenant_id=verified.tenant_id,
        customer_id=verified.customer_id,
        role=Role.CUSTOMER,
        actor_type="customer",
        actor_id=verified.customer_id,
    )


def require_staff(request: Request) -> StaffActor:
    """Return the support agent from the verified token. A customer is forbidden."""
    verified = _verified(request)
    if verified.role is not Role.SUPPORT_AGENT or verified.agent_id is None:
        _deny(request, "forbidden")
        raise SupportError("forbidden", "That action is not available.", 403)
    return StaffActor(
        tenant_id=verified.tenant_id,
        agent_id=verified.agent_id,
        display_name=display_name_for(
            role=Role.SUPPORT_AGENT,
            tenant_id=verified.tenant_id,
            customer_id=None,
            agent_id=verified.agent_id,
        ),
        actor_type="support_agent",
    )


def current_token(request: Request) -> VerifiedToken:
    """Return the verified token for a route that accepts either role."""
    return _verified(request)


def correlation_id(
    request: Request,
    x_correlation_id: Annotated[str | None, Header()] = None,
) -> str:
    """Use the caller id when present. Otherwise the API assigns one."""
    if x_correlation_id is not None and x_correlation_id.strip() != "":
        value = x_correlation_id.strip()
    else:
        value = str(uuid4())
    request.state.correlation_id = value
    return value


def get_session(request: Request) -> Iterator[Session]:
    engine = cast(Engine, request.app.state.engine)
    session = Session(engine)
    lock = getattr(request.app.state, "sqlite_lock", None)
    try:
        with lock if lock is not None else nullcontext():
            try:
                yield session
                session.commit()
                publisher = getattr(request.app.state, "event_publisher", None)
                if publisher is not None:
                    publish_outbox(session, publisher)
            except Exception:
                session.rollback()
                raise
    finally:
        session.close()
        # Yield dependencies finish after the response body is sent. Wake the
        # worker after this thread has dropped the database lock.
        events = getattr(request.app.state, "events", None)
        if isinstance(events, InMemoryEventQueue):
            events.release()


def _verified(request: Request) -> VerifiedToken:
    token = _bearer(request)
    if token is None:
        _deny(request, "missing_token")
        raise SupportError("unauthorized", "Sign in is required.", 401)
    verifier = getattr(request.app.state, "token_verifier", None)
    if not isinstance(verifier, TokenVerifier):
        _deny(request, "missing_token")
        raise SupportError("unauthorized", "Sign in is required.", 401)
    try:
        return verifier.verify(token)
    except TokenError as exc:
        _deny(request, exc.code)
        raise SupportError(exc.code, exc.message, exc.status_code) from None


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header is not None:
        scheme, _, value = header.partition(" ")
        if scheme.lower() == "bearer" and value.strip() != "":
            return value.strip()
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie is not None and cookie.strip() != "":
        return cookie.strip()
    return None


def _deny(request: Request, reason: str) -> None:
    """Record a denial without the raw token or the cookie."""
    logger.info(
        "authorization_denied",
        reason=reason,
        method=request.method,
        path=request.url.path,
    )


def page_query(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> PageQuery:
    if cursor is not None and cursor.strip() == "":
        cursor = None
    return PageQuery(limit=limit, cursor=cursor)
