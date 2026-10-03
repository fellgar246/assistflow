"""Application quotas. Callers ask this module before a provider, tool, or memory write."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Lock

SESSION_QUOTA_MESSAGE = (
    "The assistant has reached its daily session limit. Please try again tomorrow, "
    "or wait for a person."
)
TOOL_QUOTA_MESSAGE = (
    "This conversation has reached its tool-call limit. "
    "Please start a new conversation, or wait for a person."
)
TOKEN_QUOTA_MESSAGE = (
    "That message is too long to process. Please send a shorter question, or wait for a person."
)


class QuotaDenied(Exception):
    """A quota refused the work. The provider call has not started."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class QuotaLimits:
    """Caps from configuration. Domain code does not scatter these numbers."""

    def __init__(
        self,
        *,
        max_agent_steps: int = 8,
        max_tool_calls_per_turn: int = 5,
        max_model_calls_per_turn: int = 4,
        max_retrievals_per_turn: int = 2,
        max_session_minutes: int = 20,
        max_output_tokens: int = 800,
        max_sessions_per_day: int = 25,
        max_tool_calls_per_session: int = 15,
        max_input_tokens_per_call: int = 6000,
        max_output_tokens_per_call: int = 800,
        max_memory_events_per_session: int = 30,
    ) -> None:
        self.max_agent_steps = max_agent_steps
        self.max_tool_calls_per_turn = max_tool_calls_per_turn
        self.max_model_calls_per_turn = max_model_calls_per_turn
        self.max_retrievals_per_turn = max_retrievals_per_turn
        self.max_session_minutes = max_session_minutes
        self.max_output_tokens = max_output_tokens
        self.max_sessions_per_day = max_sessions_per_day
        self.max_tool_calls_per_session = max_tool_calls_per_session
        self.max_input_tokens_per_call = max_input_tokens_per_call
        self.max_output_tokens_per_call = max_output_tokens_per_call
        self.max_memory_events_per_session = max_memory_events_per_session


def under_cap(used: int, limit: int) -> bool:
    """True when another unit of work is still inside the cap."""
    return used < limit


def provider_call_allowed(
    input_tokens: int,
    requested_output_tokens: int,
    *,
    max_input_tokens: int,
    max_output_tokens: int,
) -> bool:
    """False when a token ceiling would be exceeded. Callers stop before the provider."""
    if input_tokens > max_input_tokens:
        return False
    return requested_output_tokens <= max_output_tokens


def provider_refusal(
    input_tokens: int,
    requested_output_tokens: int,
    *,
    max_input_tokens: int,
    max_output_tokens: int,
) -> str | None:
    """Return a denial message when the token ceiling refuses the provider call."""
    if provider_call_allowed(
        input_tokens,
        requested_output_tokens,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
    ):
        return None
    return TOKEN_QUOTA_MESSAGE


def memory_event_allowed(active_count: int, limit: int) -> bool:
    """False when another session event would pass the cap."""
    return active_count < limit


def session_window(max_session_minutes: int) -> timedelta:
    """How long one session's memory events stay readable."""
    if max_session_minutes < 1:
        raise ValueError("MAX_SESSION_MINUTES must be at least 1.")
    return timedelta(minutes=max_session_minutes)


class SessionQuota:
    """Count hosted sessions started on the current UTC day.

    Reserving a session happens before the remote call. A failed call does not
    return the slot. The same session id can continue without taking a second slot.
    A refused session is not stored, so a later try of that id is still a new session.
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

    def used(self) -> int:
        """Sessions reserved on the current UTC day."""
        bucket = self._days.get(self._now().date().isoformat(), set())
        return len(bucket)


class ExecutionQuota:
    """Session, tool, and token ceilings shared by the runner, gateway, and memory."""

    def __init__(
        self,
        limits: QuotaLimits,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.limits = limits
        self._sessions = SessionQuota(limits.max_sessions_per_day, now=now)
        self._tool_calls: dict[str, int] = {}
        self._lock = Lock()

    def reserve(self, session_id: str) -> bool:
        """Reserve a session before a provider call. False means the daily cap is full."""
        return self._sessions.reserve(session_id)

    def require_session(self, session_id: str) -> None:
        """Reserve a session or raise. The caller must not start a model call after this."""
        if not self.reserve(session_id):
            raise QuotaDenied("session_quota_exceeded", SESSION_QUOTA_MESSAGE)

    def claim_tool_call(self, session_id: str) -> str | None:
        """Reserve one tool call. Return a denial message when the session cap is full."""
        with self._lock:
            used = self._tool_calls.get(session_id, 0)
            if not under_cap(used, self.limits.max_tool_calls_per_session):
                return TOOL_QUOTA_MESSAGE
            self._tool_calls[session_id] = used + 1
        return None

    def tool_calls_used(self) -> int:
        """Tool calls reserved across sessions in this process."""
        with self._lock:
            return sum(self._tool_calls.values())

    def sessions_used(self) -> int:
        """Sessions reserved today."""
        return self._sessions.used()
