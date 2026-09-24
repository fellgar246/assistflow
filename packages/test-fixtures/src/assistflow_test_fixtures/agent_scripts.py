"""Scripted plans for the local assistant.

The HTTP router does not branch on customer text. The runner asks this catalog
which plan to follow.
"""

import re

from assistflow_contracts.agent import ScriptedPlan, ScriptedStep, StepKind

ASK_FOR_ORDER_NUMBER = (
    "Please send the order number from your confirmation. "
    "I have not looked up a delivery date or location. "
    "You can narrow the question, or wait for a person."
)

ORDER_NUMBER_RECEIVED = (
    "Thanks. I have not confirmed a delivery date or location for that order. "
    "Please narrow what you need, or wait for a person."
)

FALLBACK_MESSAGE = (
    "I can help with an order or a delivery question. "
    "Send an order number, or wait for a person. "
    "I have not looked up an order, delivery, return, or refund."
)

_ORDER_HINTS = ("order", "delivery", "shipment", "tracking", "where is")
_ORDER_NUMBER = re.compile(r"\bORD-\d+\b", re.IGNORECASE)


def select_script(customer_message: str) -> ScriptedPlan:
    """Pick the order-status plan or the fallback plan from the customer text."""
    lowered = customer_message.lower()
    if any(hint in lowered for hint in _ORDER_HINTS):
        return order_status_plan(customer_message)
    return fallback_plan()


def order_status_plan(customer_message: str) -> ScriptedPlan:
    steps = [ScriptedStep(kind=StepKind.MODEL, summary="order status request")]
    found = _ORDER_NUMBER.search(customer_message)
    if found is None:
        return ScriptedPlan(assistant_message=ASK_FOR_ORDER_NUMBER, steps=steps)
    order_number = found.group(0).upper()
    steps.append(
        ScriptedStep(
            kind=StepKind.TOOL_PROPOSAL,
            summary="proposed get_order",
            tool_name="get_order",
            arguments={"order_number": order_number},
        )
    )
    return ScriptedPlan(assistant_message=ORDER_NUMBER_RECEIVED, steps=steps)


def fallback_plan() -> ScriptedPlan:
    return ScriptedPlan(
        assistant_message=FALLBACK_MESSAGE,
        steps=[ScriptedStep(kind=StepKind.MODEL, summary="fallback request")],
    )
