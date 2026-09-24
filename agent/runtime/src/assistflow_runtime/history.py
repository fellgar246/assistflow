"""Bound the history window passed into a turn.

The window keeps the newest 20 messages. It also drops the oldest message
while a 4-characters-per-token estimate of the window exceeds 4000 tokens.
The newest history message is kept even when it alone exceeds that estimate.
Older messages stay in the database. The new customer message is not part of
this window; the caller passes it separately.
"""

from assistflow_contracts.agent import HistoryMessage

HISTORY_MESSAGE_CAP = 20
HISTORY_TOKEN_CAP = 4000


def estimate_tokens(text: str) -> int:
    """Estimate tokens as one token per four characters, with a floor of one."""
    if text == "":
        return 0
    return max(1, (len(text) + 3) // 4)


def bound_history(
    messages: list[HistoryMessage],
    *,
    message_cap: int = HISTORY_MESSAGE_CAP,
    token_cap: int = HISTORY_TOKEN_CAP,
) -> list[HistoryMessage]:
    """Return the newest messages that fit the message cap and the token estimate."""
    window = list(messages[-message_cap:])
    while len(window) > 1 and _token_total(window) > token_cap:
        window = window[1:]
    return window


def _token_total(messages: list[HistoryMessage]) -> int:
    return sum(estimate_tokens(message.content) for message in messages)
