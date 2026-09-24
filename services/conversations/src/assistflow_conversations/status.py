"""Allowed conversation status moves.

The table is closed. A caller that needs a new edge adds it here and covers it
with a test. Same-status calls are rejected.

| From              | To                |
| open              | waiting_approval  |
| open              | escalated         |
| open              | resolved          |
| waiting_approval  | open              |
| waiting_approval  | escalated         |
| waiting_approval  | resolved          |
| escalated         | waiting_approval  |
| escalated         | resolved          |
| resolved          | (none)            |
"""

from assistflow_contracts.conversation import ConversationStatus
from assistflow_customers.errors import SupportError

ALLOWED_TRANSITIONS: dict[ConversationStatus, frozenset[ConversationStatus]] = {
    ConversationStatus.OPEN: frozenset(
        {
            ConversationStatus.WAITING_APPROVAL,
            ConversationStatus.ESCALATED,
            ConversationStatus.RESOLVED,
        }
    ),
    ConversationStatus.WAITING_APPROVAL: frozenset(
        {
            ConversationStatus.OPEN,
            ConversationStatus.ESCALATED,
            ConversationStatus.RESOLVED,
        }
    ),
    ConversationStatus.ESCALATED: frozenset(
        {
            ConversationStatus.WAITING_APPROVAL,
            ConversationStatus.RESOLVED,
        }
    ),
    ConversationStatus.RESOLVED: frozenset(),
}


def transition_status(
    current: ConversationStatus, target: ConversationStatus
) -> ConversationStatus:
    """Return the target status when the move is allowed."""
    if target not in ALLOWED_TRANSITIONS[current]:
        raise SupportError(
            "invalid_conversation_status",
            f"Cannot move a conversation from {current.value} to {target.value}.",
            409,
        )
    return target
