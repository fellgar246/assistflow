"""Publish outbox rows after commit. Consumers stay off the request thread."""

from __future__ import annotations

from collections.abc import Callable, MutableMapping
from typing import Any
from uuid import UUID

import structlog
from assistflow_conversations.outbox import DomainEvent, EventPublisher, OutboxRepository
from assistflow_conversations.side_effects import apply_side_effects
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from starlette.types import ASGIApp, Receive, Scope, Send

from assistflow_api.config import Settings
from assistflow_api.event_queue import InMemoryEventQueue
from assistflow_api.sqlite_lock import lock_for

logger = structlog.get_logger(__name__)


def make_handler(engine: Engine, settings: Settings) -> Callable[[DomainEvent], None]:
    """Return the consumer used by the in-process worker."""
    lock = lock_for(engine)

    def handle(event: DomainEvent) -> None:
        if lock is None:
            _apply(engine, settings, event)
            return
        with lock:
            _apply(engine, settings, event)

    return handle


def build_publisher(settings: Settings, memory: InMemoryEventQueue) -> EventPublisher:
    """Use the in-memory queue unless hosted workers are explicitly enabled."""
    if settings.aws_enabled and settings.async_workers_enabled and not settings.local_only_mode:
        from assistflow_api.aws_events import AwsEventPublisher

        return AwsEventPublisher(
            region=settings.aws_region,
            bus_name=settings.event_bus_name,
            queue_url=settings.event_queue_url,
        )
    return memory


def publish_outbox(session: Session, publisher: EventPublisher) -> None:
    """Send pending rows. A broker error is logged and leaves the row for retry.

    The business transaction has already committed. This function does not raise.
    """
    try:
        pending = OutboxRepository(session).pending()
    except Exception:
        logger.exception("event_outbox_read_failed")
        session.rollback()
        return
    for record in pending:
        event = record.to_event()
        try:
            publisher.publish(event)
        except Exception:
            logger.exception(
                "event_publish_failed",
                event_id=str(event.event_id),
                event_name=event.name,
                tenant_id=str(event.tenant_id),
            )
            _record_failure(session, event.event_id)
            continue
        try:
            OutboxRepository(session).mark_published(event.event_id)
            session.commit()
        except Exception:
            logger.exception("event_outbox_mark_failed", event_id=str(event.event_id))
            session.rollback()


def _apply(engine: Engine, settings: Settings, event: DomainEvent) -> None:
    with Session(engine) as session:
        apply_side_effects(session, event, sample_rate=settings.eval_sample_rate)


def _record_failure(session: Session, event_id: UUID) -> None:
    try:
        OutboxRepository(session).record_failure(event_id)
        session.commit()
    except Exception:
        logger.exception("event_outbox_failure_unrecorded", event_id=str(event_id))
        session.rollback()


class ReleaseSideEffects:
    """Move queued events to the worker after the response body is sent."""

    def __init__(self, app: ASGIApp, queue: InMemoryEventQueue) -> None:
        self.app = app
        self._queue = queue

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        released = False

        async def send_wrapper(message: MutableMapping[str, Any]) -> None:
            nonlocal released
            await send(message)
            if released or message.get("type") != "http.response.body":
                return
            if message.get("more_body", False):
                return
            released = True
            self._queue.release()

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if not released:
                self._queue.release()
