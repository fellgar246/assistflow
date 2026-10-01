"""Facts worth remembering from a tool result. Raw payloads are not stored."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from assistflow_contracts.agent import ExecutedTool

from assistflow_memory.local_session import ORDER_KIND, SHIPMENT_KIND
from assistflow_memory.ports import SessionMemory

_ORDER = re.compile(r"^ORD-\d+$")
_STATUSES = frozenset({"pending", "in_transit", "out_for_delivery", "delivered", "exception"})


def remember_tool_facts(
    port: SessionMemory,
    tenant_id: UUID,
    customer_id: UUID,
    conversation_id: UUID,
    executed: list[ExecutedTool],
    now: datetime,
) -> None:
    """Record the newest order id and shipment status from this turn."""
    order_id, status = extract_session_facts(executed)
    if order_id is not None:
        port.record(tenant_id, customer_id, conversation_id, ORDER_KIND, order_id, now)
    if status is not None:
        port.record(tenant_id, customer_id, conversation_id, SHIPMENT_KIND, status, now)


def extract_session_facts(executed: list[ExecutedTool]) -> tuple[str | None, str | None]:
    """Read an order id and a shipment status. Other fields are ignored."""
    order_id: str | None = None
    status: str | None = None
    for item in executed:
        body = item.body if isinstance(item.body, dict) else {}
        found = _order_id(body)
        if found is not None:
            order_id = found
        found_status = _status(item.name, body)
        if found_status is not None:
            status = found_status
    return order_id, status


def _order_id(body: dict[str, Any]) -> str | None:
    candidate = body.get("order_id")
    if isinstance(candidate, str) and _ORDER.fullmatch(candidate):
        return candidate
    change = body.get("proposed_change")
    if isinstance(change, dict):
        number = change.get("order_number")
        if isinstance(number, str) and _ORDER.fullmatch(number):
            return number
    return None


def _status(tool_name: str, body: dict[str, Any]) -> str | None:
    shipment = body.get("shipment")
    if isinstance(shipment, dict):
        nested = shipment.get("status")
        if isinstance(nested, str) and nested in _STATUSES:
            return nested
    if tool_name == "get_shipment":
        raw = body.get("status")
        if isinstance(raw, str) and raw in _STATUSES:
            return raw
    return None
