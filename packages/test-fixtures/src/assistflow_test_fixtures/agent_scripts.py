"""Scripted plans for the local assistant.

The HTTP router does not branch on customer text. The runner asks this catalog
which plan to follow. After a tool result exists, the reply uses only those facts.
"""

import re
from typing import Any
from uuid import uuid4

from assistflow_contracts.agent import ProposedToolCall, ScriptedPlan, ScriptedStep, StepKind
from assistflow_contracts.memory import ScriptContext

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
_ESCALATION_PHRASES = (
    "speak to a person",
    "talk to a person",
    "talk to a human",
    "human agent",
    "real person",
    "escalate this",
)


def select_script(customer_message: str, context: ScriptContext | None = None) -> ScriptedPlan:
    """Pick a plan from the customer text. Sensitive plans only propose a change."""
    lowered = customer_message.lower()
    if _is_escalation(lowered):
        return escalation_plan(customer_message)
    if _is_address_change(lowered):
        return address_change_plan(customer_message, context)
    if _is_refund_request(lowered):
        return refund_plan(customer_message, context)
    if _is_return_request(lowered):
        return return_plan(customer_message, context)
    if any(hint in lowered for hint in _ORDER_HINTS):
        return order_status_plan(customer_message, context)
    return policy_plan(customer_message)


def address_change_plan(
    customer_message: str, context: ScriptContext | None = None
) -> ScriptedPlan:
    """Propose one address change. The reply does not claim it already happened."""
    steps = [ScriptedStep(kind=StepKind.MODEL, summary="address change request")]
    order_number = resolve_order_number(customer_message, context)
    if order_number is None:
        return ScriptedPlan(
            assistant_message=(
                "Please send the order number for the delivery address you want to change. "
                "Nothing has changed yet."
            ),
            steps=steps,
        )
    steps.append(
        ScriptedStep(
            kind=StepKind.TOOL_PROPOSAL,
            summary="proposed update_shipping_address",
            tool_name="update_shipping_address",
            arguments={
                "order_id": order_number,
                "new_address": _proposed_address(customer_message),
                "idempotency_key": f"address:{order_number}:{uuid4()}",
            },
        )
    )
    return ScriptedPlan(
        assistant_message=(
            f"Here is the delivery address change I can make for {order_number}. "
            "Please review and confirm. Nothing has changed yet."
        ),
        steps=steps,
    )


def return_plan(customer_message: str, context: ScriptContext | None = None) -> ScriptedPlan:
    """Propose a return. The application still has to confirm it."""
    steps = [ScriptedStep(kind=StepKind.MODEL, summary="return request")]
    order_number = resolve_order_number(customer_message, context)
    if order_number is None:
        return ScriptedPlan(
            assistant_message=(
                "Please send the order number you want to return. Nothing has changed yet."
            ),
            steps=steps,
        )
    steps.append(
        ScriptedStep(
            kind=StepKind.TOOL_PROPOSAL,
            summary="proposed create_return_request",
            tool_name="create_return_request",
            arguments={
                "order_id": order_number,
                "reason_code": _reason_code(customer_message),
                "idempotency_key": f"return:{order_number}:{uuid4()}",
            },
        )
    )
    return ScriptedPlan(
        assistant_message=(
            f"Here is the return I can start for {order_number}. "
            "Please review and confirm. Nothing has changed yet."
        ),
        steps=steps,
    )


def refund_plan(customer_message: str, context: ScriptContext | None = None) -> ScriptedPlan:
    """Propose a refund request. The amount is not a payment."""
    steps = [ScriptedStep(kind=StepKind.MODEL, summary="refund request")]
    order_number = resolve_order_number(customer_message, context)
    if order_number is None:
        return ScriptedPlan(
            assistant_message=(
                "Please send the order number for the refund request. "
                "This is a request, not a payment, and nothing has changed yet."
            ),
            steps=steps,
        )
    steps.append(
        ScriptedStep(
            kind=StepKind.TOOL_PROPOSAL,
            summary="proposed create_refund_request",
            tool_name="create_refund_request",
            arguments={
                "order_id": order_number,
                "amount_cents": _amount_cents(customer_message),
                "reason_code": _reason_code(customer_message),
                "idempotency_key": f"refund:{order_number}:{uuid4()}",
            },
        )
    )
    return ScriptedPlan(
        assistant_message=(
            f"Here is the refund request I can submit for {order_number}. "
            "Please review and confirm. This is a request, not a payment, "
            "and nothing has changed yet."
        ),
        steps=steps,
    )


def escalation_plan(customer_message: str) -> ScriptedPlan:
    """Ask a person to join. The application still checks the conversation."""
    reason = customer_message.strip()[:500]
    return ScriptedPlan(
        assistant_message=(
            "I can ask a person to join this conversation. "
            "I have not changed an order, a delivery, a return, or a refund."
        ),
        steps=[
            ScriptedStep(kind=StepKind.MODEL, summary="human escalation"),
            ScriptedStep(
                kind=StepKind.TOOL_PROPOSAL,
                summary="proposed request_human_escalation",
                tool_name="request_human_escalation",
                arguments={
                    "reason": reason,
                    "idempotency_key": f"escalate:{uuid4()}",
                },
            ),
        ],
    )


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


def order_status_plan(customer_message: str, context: ScriptContext | None = None) -> ScriptedPlan:
    steps = [ScriptedStep(kind=StepKind.MODEL, summary="order status request")]
    order_number = resolve_order_number(customer_message, context)
    if order_number is None:
        return ScriptedPlan(assistant_message=ASK_FOR_ORDER_NUMBER, steps=steps)
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
    escalation = _succeeded(outcomes, "request_human_escalation")
    if isinstance(escalation, dict):
        return (
            "A person will join this conversation. "
            "I have not changed an order, a delivery, a return, or a refund."
        )
    order = _succeeded(outcomes, "get_order")
    shipment = _succeeded(outcomes, "get_shipment")
    profile = _succeeded(outcomes, "get_customer_profile")
    ticket = _succeeded(outcomes, "get_ticket")
    sentences: list[str] = []
    if isinstance(order, dict):
        sentences.append(f"Order {order.get('order_id')} is {order.get('status')}.")
        sentences.append(f"The total is {order.get('total_cents')} {order.get('currency')}.")
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
        return "I could not find that record. I have not confirmed a delivery date or location."
    if any(item.get("status") == "blocked" for item in outcomes):
        return "I cannot complete that lookup. Please narrow the request, or wait for a person."
    return "I could not complete that lookup. Please try again, or wait for a person."


def _is_escalation(text: str) -> bool:
    return any(phrase in text for phrase in _ESCALATION_PHRASES)


def _is_address_change(text: str) -> bool:
    return "address" in text and any(word in text for word in ("change", "update", "move"))


def _is_refund_request(text: str) -> bool:
    return "policy" not in text and "refund" in text


def _is_return_request(text: str) -> bool:
    if "policy" in text or not re.search(r"\breturn\b", text):
        return False
    return any(word in text for word in ("start", "request", "want", "open"))


def resolve_order_number(customer_message: str, context: ScriptContext | None = None) -> str | None:
    """Prefer the message, then session memory, then the bounded history window."""
    explicit = _order_number(customer_message)
    if explicit is not None:
        return explicit
    if context is not None:
        remembered = _order_number(context.last_order_id or "")
        if remembered is not None:
            return remembered
        for text in reversed(context.history):
            found = _order_number(text)
            if found is not None:
                return found
    return None


def _order_number(customer_message: str) -> str | None:
    found = _ORDER_NUMBER.search(customer_message)
    if found is None:
        return None
    return found.group(0).upper()


def _proposed_address(customer_message: str) -> dict[str, str]:
    address = {
        "recipient": "Ava Chen",
        "line1": "42 Congress Avenue",
        "city": "Austin",
        "region": "TX",
        "postal_code": "78701",
        "country": "US",
    }
    for key in ("recipient", "line1", "line2", "city", "region", "postal_code", "country"):
        match = re.search(rf"(?im)^{key}\s*:\s*(.+)$", customer_message)
        if match is not None and match.group(1).strip() != "":
            address[key] = match.group(1).strip()
    return address


def _reason_code(customer_message: str) -> str:
    match = re.search(r"(?im)^reason(?:_code)?\s*:\s*([a-z_]+)\s*$", customer_message)
    if match is None:
        return "damaged"
    return match.group(1)


def _amount_cents(customer_message: str) -> int:
    match = re.search(r"(?im)^amount_cents\s*:\s*(\d+)\s*$", customer_message)
    if match is None:
        return 1500
    return int(match.group(1))


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
