"""Fixed follow-ups used to compare session memory on and off."""

from dataclasses import dataclass

from assistflow_contracts.memory import ScriptContext

from assistflow_test_fixtures.agent_scripts import address_change_plan

ASK = "ask"


@dataclass(frozen=True)
class FollowUpCase:
    """One address follow-up. `expected` is an order id or `ask`."""

    name: str
    history: tuple[str, ...]
    session_order_id: str | None
    message: str
    expected: str


FOLLOW_UPS: tuple[FollowUpCase, ...] = (
    FollowUpCase(
        "session and history agree",
        ("Where is my order ORD-10482?",),
        "ORD-10482",
        "change it to this address",
        "ORD-10482",
    ),
    FollowUpCase(
        "history still holds the order",
        ("Where is my order ORD-10482?",),
        None,
        "please update the delivery address",
        "ORD-10482",
    ),
    FollowUpCase(
        "history cleared and session remembers",
        (),
        "ORD-10482",
        "change it to this address",
        "ORD-10482",
    ),
    FollowUpCase(
        "nothing identifies an order",
        (),
        None,
        "change it to this address",
        ASK,
    ),
    FollowUpCase(
        "session wins over a different history id",
        ("Earlier I mentioned ORD-20817 by mistake",),
        "ORD-10482",
        "move it to this address",
        "ORD-10482",
    ),
    FollowUpCase(
        "the current message names the order",
        ("Where is ORD-10482?",),
        "ORD-10482",
        "change the address on ORD-20817",
        "ORD-20817",
    ),
    FollowUpCase(
        "history window is enough",
        ("status of ORD-10482 please",),
        None,
        "I want to change the shipping address",
        "ORD-10482",
    ),
    FollowUpCase(
        "recent history dropped the order",
        ("thanks", "ok"),
        "ORD-10482",
        "update the address",
        "ORD-10482",
    ),
    FollowUpCase(
        "ambiguous with no memory",
        ("thanks",),
        None,
        "please move the delivery address",
        ASK,
    ),
    FollowUpCase(
        "shipment note still names the order",
        ("The shipment for ORD-10482 is in transit",),
        "ORD-10482",
        "change it to this address",
        "ORD-10482",
    ),
)


def follow_up_choice(case: FollowUpCase, *, memory_enabled: bool) -> str:
    """Resolve one follow-up the same way the scripted assistant does."""
    context = ScriptContext(
        history=list(case.history),
        last_order_id=case.session_order_id if memory_enabled else None,
    )
    plan = address_change_plan(case.message, context)
    for step in plan.steps:
        if step.tool_name != "update_shipping_address":
            continue
        order_id = step.arguments.get("order_id")
        if isinstance(order_id, str):
            return order_id
    return ASK


def score_follow_ups(*, memory_enabled: bool) -> int:
    """Count follow-ups that match the expected order, or that correctly ask."""
    return sum(
        1
        for case in FOLLOW_UPS
        if follow_up_choice(case, memory_enabled=memory_enabled) == case.expected
    )
