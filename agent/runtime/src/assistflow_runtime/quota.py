"""Daily hosted-session quota. A reserved session is never released."""

from collections.abc import Callable
from datetime import UTC, datetime


class SessionQuota:
    """Count hosted sessions started on the current UTC day.

    Reserving a session happens before the remote call. A failed call does not
    return the slot. The same session id can continue without taking a second slot.
    """

    def __init__(
        self,
        max_sessions_per_day: int,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._limit = max_sessions_per_day
        self._now = now or (lambda: datetime.now(UTC))
        self._days: dict[str, set[str]] = {}

    def reserve(self, session_id: str) -> bool:
        """Reserve one new session. Return false when the daily cap is already full."""
        bucket = self._days.setdefault(self._now().date().isoformat(), set())
        if session_id in bucket:
            return True
        if len(bucket) >= self._limit:
            return False
        bucket.add(session_id)
        return True
