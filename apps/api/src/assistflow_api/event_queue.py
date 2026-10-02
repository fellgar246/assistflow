"""In-memory queue. Publish records a message. Handlers run after the response."""

from __future__ import annotations

import threading
from collections.abc import Callable

import structlog
from assistflow_conversations.outbox import DomainEvent

logger = structlog.get_logger(__name__)

Handler = Callable[[DomainEvent], None]


class InMemoryEventQueue:
    """Hold events until `release`, then run handlers on a background thread.

    `publish` does not call the handler. `drain` runs held events on the caller
    and is the test helper for the local adapter.
    """

    def __init__(self, handler: Handler) -> None:
        self._handler = handler
        self._held: list[DomainEvent] = []
        self._visible: list[DomainEvent] = []
        self._retry: list[DomainEvent] = []
        self._published: list[DomainEvent] = []
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._idle = threading.Event()
        self._idle.set()
        self._stop = False
        self._thread: threading.Thread | None = None

    def publish(self, event: DomainEvent) -> None:
        """Record one message. The handler is not called here."""
        with self._lock:
            self._published.append(event)
            self._held.append(event)

    def release(self) -> None:
        """Make held messages visible to the background worker. Does not run handlers."""
        with self._wake:
            if not self._held:
                return
            self._visible.extend(self._held)
            self._held.clear()
            self._idle.clear()
            self._wake.notify()

    def start(self) -> None:
        """Start the worker thread once."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="side-effects", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Ask the worker to exit and wait briefly."""
        with self._wake:
            self._stop = True
            self._wake.notify_all()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2)

    def drain(self) -> int:
        """Run handlers for messages that have not been taken by the worker."""
        with self._lock:
            batch = [*self._held, *self._visible]
            self._held.clear()
            self._visible.clear()
        for event in batch:
            self._handler(event)
        return len(batch)

    def set_handler(self, handler: Handler) -> None:
        with self._lock:
            self._handler = handler

    def published(self) -> list[DomainEvent]:
        with self._lock:
            return list(self._published)

    def retryable(self) -> list[DomainEvent]:
        """Messages whose handler failed and can be delivered again."""
        with self._lock:
            return list(self._retry)

    def wait_until_idle(self, timeout: float = 2.0) -> bool:
        return self._idle.wait(timeout)

    def _loop(self) -> None:
        while True:
            with self._wake:
                while not self._visible and not self._stop:
                    self._idle.set()
                    self._wake.wait()
                if self._stop and not self._visible:
                    self._idle.set()
                    return
                event = self._visible.pop(0)
                handler = self._handler
                self._idle.clear()
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "side_effect_consumer_failed",
                    event_id=str(event.event_id),
                    event_name=event.name,
                )
                with self._lock:
                    self._retry.append(event)
