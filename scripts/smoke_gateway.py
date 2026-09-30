"""Call tools/list and tools/call on the hosted gateway.

The command skips when the gateway URL or credentials are missing.
It does not print credentials.
"""

import os
import sys
from uuid import UUID

from assistflow_contracts.gateway import GatewayActor

from assistflow_runtime.gateway import build_agentcore_gateway

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
HARBOR_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001")
ORDER_NUMBER = "ORD-10482"


def ready() -> bool:
    """True when an operator supplied a gateway URL and a credential."""
    if os.environ.get("AGENTCORE_GATEWAY_URL", "").strip() == "":
        return False
    if os.environ.get("AGENTCORE_ACTOR_CONTEXT_SECRET", "").strip() == "":
        return False
    token = os.environ.get("AGENTCORE_GATEWAY_TOKEN", "").strip()
    access_key = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
    profile = os.environ.get("AWS_PROFILE", "").strip()
    return token != "" or access_key != "" or profile != ""


def main() -> int:
    """Return 0 when smoke passes or when credentials are absent."""
    if not ready():
        print("Hosted gateway smoke skipped.")
        return 0
    gateway = build_agentcore_gateway(
        url=os.environ["AGENTCORE_GATEWAY_URL"].strip(),
        token=os.environ.get("AGENTCORE_GATEWAY_TOKEN", "").strip(),
        secret=os.environ["AGENTCORE_ACTOR_CONTEXT_SECRET"].strip(),
    )
    names = {tool.name for tool in gateway.list_tools()}
    if "get_order" not in names or "issue_payment" in names:
        print("Hosted gateway smoke failed: tools/list did not advertise the read tools.")
        return 1
    actor = GatewayActor(
        tenant_id=HARBOR,
        customer_id=HARBOR_CUSTOMER,
        actor_type="customer",
        correlation_id="smoke-gateway",
        conversation_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccc0109"),
    )
    outcome = gateway.call_tool("get_order", {"order_id": ORDER_NUMBER}, actor)
    if outcome.status != "succeeded" or not isinstance(outcome.body, dict):
        print("Hosted gateway smoke failed: tools/call did not return an order.")
        return 1
    shipment = outcome.body.get("shipment")
    hub = shipment.get("origin_hub") if isinstance(shipment, dict) else None
    delivery = shipment.get("estimated_delivery_on") if isinstance(shipment, dict) else None
    if outcome.body.get("order_id") != ORDER_NUMBER or hub != "DFW" or delivery != "2099-06-15":
        print(
            "Hosted gateway smoke failed: "
            f"order={outcome.body.get('order_id')} hub={hub} delivery={delivery}"
        )
        return 1
    print("Hosted gateway smoke matched the seeded order.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
