"""Domain facts taken from tool results. Model prose is not a source of truth."""

from typing import Any

from assistflow_contracts.agent import AgentResult
from pydantic import BaseModel, ConfigDict, Field


class DomainFacts(BaseModel):
    """Order facts a smoke check can compare without matching model wording."""

    model_config = ConfigDict(frozen=True)

    order_status: str | None = None
    origin_hub: str | None = None
    estimated_delivery_on: str | None = None
    tool_names: list[str] = Field(default_factory=list)


def domain_facts(result: AgentResult) -> DomainFacts:
    """Read status, hub, delivery date, and tool names from executed tool bodies."""
    order_status: str | None = None
    origin_hub: str | None = None
    estimated_delivery_on: str | None = None
    for item in result.executed_tools:
        body = item.body if isinstance(item.body, dict) else {}
        if item.name == "get_order":
            order_status = _text(body.get("status")) or order_status
            shipment = body.get("shipment")
            if isinstance(shipment, dict):
                origin_hub = _text(shipment.get("origin_hub")) or origin_hub
                estimated_delivery_on = _text(shipment.get("estimated_delivery_on")) or (
                    estimated_delivery_on
                )
        if item.name == "get_shipment":
            origin_hub = _text(body.get("origin_hub")) or origin_hub
            delivery = _text(body.get("estimated_delivery_on"))
            estimated_delivery_on = delivery or estimated_delivery_on
    return DomainFacts(
        order_status=order_status,
        origin_hub=origin_hub,
        estimated_delivery_on=estimated_delivery_on,
        tool_names=[item.name for item in result.executed_tools],
    )


def order_facts_from_fixture(document: dict[str, Any], order_number: str) -> DomainFacts:
    """Expected facts for one seeded order. The lookup tool name is get_order."""
    for tenant in document.get("tenants", []):
        if not isinstance(tenant, dict):
            continue
        for order in tenant.get("orders", []):
            if not isinstance(order, dict) or order.get("order_number") != order_number:
                continue
            shipment = order.get("shipment")
            if not isinstance(shipment, dict):
                break
            return DomainFacts(
                order_status=_text(order.get("status")),
                origin_hub=_text(shipment.get("origin_hub")),
                estimated_delivery_on=_text(shipment.get("estimated_delivery_on")),
                tool_names=["get_order"],
            )
    raise ValueError(f"Fixture is missing shipment facts for {order_number}.")


def same_order_facts(actual: DomainFacts, expected: DomainFacts) -> bool:
    """Match status, hub, and delivery date. get_order must be among the tools used."""
    return (
        actual.order_status == expected.order_status
        and actual.origin_hub == expected.origin_hub
        and actual.estimated_delivery_on == expected.estimated_delivery_on
        and "get_order" in actual.tool_names
    )


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip() != "":
        return value
    return None
