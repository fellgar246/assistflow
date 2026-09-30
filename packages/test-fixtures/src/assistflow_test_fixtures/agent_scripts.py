"""Scripted plans for the local assistant.

The HTTP router does not branch on customer text. The runner asks this catalog
which plan to follow. After a tool result exists, the reply uses only those facts.
"""

import re
from typing import Any

from assistflow_contracts.agent import ProposedToolCall, ScriptedPlan, ScriptedStep, StepKind

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
    return policy_plan(customer_message)


def policy_plan(customer_message: str) -> ScriptedPlan:
    """Ask for published help articles. The application answers from those chunks."""
    query = customer_message.strip()[:400]
    return ScriptedPlan(
        assistant_message=FALLBACK_MESSAGE,
        steps=[
            ScriptedStep(kind=StepKind.MODEL, summary="policy question"),
            ScriptedStep(
                kind=StepKind.TOOL_PROPOSAL,
                summary="proposed search_support_policy",
                tool_name="search_support_policy",
                arguments={"query": query},
            ),
        ],
    )


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
            arguments={"order_id": order_number},
        )
    )
    return ScriptedPlan(assistant_message=ORDER_NUMBER_RECEIVED, steps=steps)


def follow_up_calls(
    customer_message: str, outcomes: list[dict[str, Any]]
) -> list[ProposedToolCall]:
    """Propose get_shipment when the order result has no shipment facts."""
    if any(item.get("name") == "get_shipment" for item in outcomes):
        return []
    order = next(
        (
            item
            for item in outcomes
            if item.get("name") == "get_order" and item.get("status") == "succeeded"
        ),
        None,
    )
    if order is None:
        return []
    body = order.get("body")
    if not isinstance(body, dict) or body.get("shipment"):
        return []
    lowered = customer_message.lower()
    if not any(hint in lowered for hint in ("delivery", "shipment", "tracking", "where is")):
        return []
    order_id = body.get("order_id")
    if not isinstance(order_id, str):
        return []
    return [ProposedToolCall(name="get_shipment", arguments={"order_id": order_id})]


def reply_from_tools(outcomes: list[dict[str, Any]]) -> str:
    """Answer from tool bodies only. Missing facts are not filled in."""
    order = _succeeded(outcomes, "get_order")
    shipment = _succeeded(outcomes, "get_shipment")
    profile = _succeeded(outcomes, "get_customer_profile")
    ticket = _succeeded(outcomes, "get_ticket")
    sentences: list[str] = []
    if isinstance(order, dict):
        sentences.append(f"Order {order.get('order_id')} is {order.get('status')}.")
        sentences.append(
            f"The total is {order.get('total_cents')} {order.get('currency')}."
        )
        sentences.append(
            f"It ships to {order.get('shipping_city')}, {order.get('shipping_country')}."
        )
        nested = order.get("shipment") if isinstance(order.get("shipment"), dict) else shipment
        if isinstance(nested, dict):
            sentences.append(_shipment_sentence(nested))
    elif isinstance(shipment, dict):
        sentences.append(_shipment_sentence(shipment))
    if isinstance(profile, dict):
        sentences.append(
            f"The account name is {profile.get('display_name')} "
            f"and the email is {profile.get('email')}."
        )
    if isinstance(ticket, dict):
        sentences.append(
            f"The ticket is {ticket.get('status')}, priority {ticket.get('priority')}, "
            f"category {ticket.get('category')}: {ticket.get('summary')}"
        )
    if sentences:
        return " ".join(sentences)
    if any(item.get("error_code") == "not_found" for item in outcomes):
        return (
            "I could not find that record. I have not confirmed a delivery date or location."
        )
    if any(item.get("status") == "blocked" for item in outcomes):
        return "I cannot complete that lookup. Please narrow the request, or wait for a person."
    return "I could not complete that lookup. Please try again, or wait for a person."


def _succeeded(outcomes: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for item in outcomes:
        if item.get("name") == name and item.get("status") == "succeeded":
            body = item.get("body")
            if isinstance(body, dict):
                return body
    return None


def _shipment_sentence(shipment: dict[str, Any]) -> str:
    text = f"The shipment is {shipment.get('status')}"
    hub = shipment.get("origin_hub")
    if isinstance(hub, str) and hub:
        text += f" from the {hub} hub"
    delivery = shipment.get("estimated_delivery_on")
    if isinstance(delivery, str) and delivery:
        text += f", with an estimated delivery date of {delivery}"
    carrier = shipment.get("carrier_name")
    if isinstance(carrier, str) and carrier:
        text += f", carried by {carrier}"
    return text + "."


def fallback_plan() -> ScriptedPlan:
    return ScriptedPlan(
        assistant_message=FALLBACK_MESSAGE,
        steps=[ScriptedStep(kind=StepKind.MODEL, summary="fallback request")],
    )
