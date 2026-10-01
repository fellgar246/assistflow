"""Choose local tables or a hosted client. Flags that are off build nothing."""

from dataclasses import dataclass

from assistflow_customers.repository import CustomerRepository
from sqlalchemy.orm import Session

from assistflow_memory.hosted import (
    AgentCorePreferenceMemory,
    AgentCoreSessionMemory,
    HostedMemoryClient,
    build_hosted_memory_client,
)
from assistflow_memory.local_preferences import LocalPreferenceMemory
from assistflow_memory.local_session import LocalSessionMemory
from assistflow_memory.ports import PreferenceMemory, SessionMemory


@dataclass(frozen=True)
class MemoryPorts:
    """Both ports are optional. Order, ticket, and approval services do not use them."""

    session: SessionMemory | None = None
    preferences: PreferenceMemory | None = None


def build_memory_ports(
    *,
    short_term_enabled: bool,
    long_term_enabled: bool,
    agentcore_enabled: bool,
    max_events: int,
    max_session_minutes: int,
    session: Session | None = None,
    region: str = "",
    memory_id: str = "",
    hosted_client: HostedMemoryClient | None = None,
) -> MemoryPorts:
    """Return the enabled adapters. A disabled flag does not construct a client."""
    if not short_term_enabled and not long_term_enabled:
        return MemoryPorts()

    client = hosted_client
    if client is None and agentcore_enabled:
        if memory_id.strip() == "":
            raise ValueError("AGENTCORE_MEMORY_ID is required when hosted memory is enabled.")
        client = build_hosted_memory_client(region)

    session_port: SessionMemory | None = None
    if short_term_enabled:
        if agentcore_enabled:
            if client is None:
                raise ValueError("A hosted memory client is required.")
            session_port = AgentCoreSessionMemory(
                client,
                memory_id,
                max_events,
                max_session_minutes,
                customers=None if session is None else _customers(session),
            )
        else:
            if session is None:
                raise ValueError("Local session memory requires a database session.")
            session_port = LocalSessionMemory(session, max_events, max_session_minutes)

    preference_port: PreferenceMemory | None = None
    if long_term_enabled:
        if agentcore_enabled:
            if client is None:
                raise ValueError("A hosted memory client is required.")
            preference_port = AgentCorePreferenceMemory(
                client,
                memory_id,
                customers=None if session is None else _customers(session),
            )
        else:
            if session is None:
                raise ValueError("Local preference memory requires a database session.")
            preference_port = LocalPreferenceMemory(session)

    return MemoryPorts(session=session_port, preferences=preference_port)


def _customers(session: Session) -> CustomerRepository:
    return CustomerRepository(session)
