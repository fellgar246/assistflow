"""Conversation status moves."""

import pytest
from assistflow_contracts.conversation import ConversationStatus
from assistflow_conversations.status import ALLOWED_TRANSITIONS, transition_status
from assistflow_customers.errors import SupportError


def test_open_can_escalate_or_resolve() -> None:
    assert transition_status(ConversationStatus.OPEN, ConversationStatus.ESCALATED) is (
        ConversationStatus.ESCALATED
    )
    assert transition_status(ConversationStatus.OPEN, ConversationStatus.RESOLVED) is (
        ConversationStatus.RESOLVED
    )
    assert transition_status(ConversationStatus.OPEN, ConversationStatus.WAITING_APPROVAL) is (
        ConversationStatus.WAITING_APPROVAL
    )


def test_resolved_is_terminal() -> None:
    for target in ConversationStatus:
        with pytest.raises(SupportError) as caught:
            transition_status(ConversationStatus.RESOLVED, target)
        assert caught.value.code == "invalid_conversation_status"


def test_every_status_has_a_documented_edge_set() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(ConversationStatus)
    assert ConversationStatus.ESCALATED in ALLOWED_TRANSITIONS[ConversationStatus.OPEN]
    assert ConversationStatus.RESOLVED in ALLOWED_TRANSITIONS[ConversationStatus.OPEN]
    assert ALLOWED_TRANSITIONS[ConversationStatus.RESOLVED] == frozenset()


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (ConversationStatus.OPEN, ConversationStatus.OPEN),
        (ConversationStatus.ESCALATED, ConversationStatus.OPEN),
        (ConversationStatus.WAITING_APPROVAL, ConversationStatus.WAITING_APPROVAL),
        (ConversationStatus.RESOLVED, ConversationStatus.OPEN),
    ],
)
def test_illegal_jumps_are_rejected(
    current: ConversationStatus, target: ConversationStatus
) -> None:
    with pytest.raises(SupportError) as caught:
        transition_status(current, target)
    assert caught.value.code == "invalid_conversation_status"
    assert caught.value.status_code == 409
