"""Load a stored conversation without calling a tool or a model."""

from dataclasses import dataclass
from uuid import UUID

from assistflow_conversations.repository import (
    ConversationRecord,
    ConversationRepository,
    MessageRecord,
    MessageRepository,
)
from assistflow_tickets.repository import TicketRepository
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class ConversationReplay:
    conversation: ConversationRecord
    messages: list[MessageRecord]
    ticket_ids: list[UUID]


def replay_conversation(
    session: Session, tenant_id: UUID, conversation_id: UUID
) -> ConversationReplay:
    """Return the conversation, its messages in creation order, and linked ticket ids."""
    conversation = ConversationRepository(session).require(tenant_id, conversation_id)
    messages = MessageRepository(session).list_all(tenant_id, conversation_id)
    tickets = TicketRepository(session).list_ids_for_conversation(tenant_id, conversation_id)
    return ConversationReplay(conversation=conversation, messages=messages, ticket_ids=tickets)
