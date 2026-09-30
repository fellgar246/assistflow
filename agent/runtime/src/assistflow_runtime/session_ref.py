"""Runtime session ids. A session id is the conversation id, never a customer email."""

from uuid import UUID


def runtime_session_id(conversation_id: UUID) -> str:
    """Return the session id for one conversation.

    The value is the conversation id. It is long enough for the hosted runtime
    and it does not contain an email address.
    """
    value = str(conversation_id)
    if "@" in value:
        raise ValueError("A runtime session id cannot be an email address.")
    return value
