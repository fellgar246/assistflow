"""Caps for one conversation's session memory."""


class MemoryLimitError(Exception):
    """The conversation already holds the maximum number of session events."""


MEMORY_LIMIT_MESSAGE = (
    "This conversation has reached its memory limit. "
    "Please start a new conversation, or wait for a person."
)
