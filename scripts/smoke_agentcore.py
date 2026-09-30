"""Compare hosted order facts with the seeded fixture.

The command skips when the runtime ARN or cloud credentials are missing.
It compares order status, hub, delivery date, and tool names.
"""

import json
import os
import sys
from pathlib import Path
from uuid import UUID

from assistflow_contracts.agent import PromptRef, TurnContext

from assistflow_runtime.facts import (
    domain_facts,
    order_facts_from_fixture,
    same_order_facts,
)
from assistflow_runtime.hosted_runner import (
    AgentCoreRuntimeRunner,
    BotoRuntimeTransport,
    build_data_plane_client,
)
from assistflow_runtime.quota import SessionQuota

HARBOR = UUID("11111111-1111-4111-8111-111111111111")
HARBOR_CUSTOMER = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001")
ORDER_NUMBER = "ORD-10482"


def ready() -> bool:
    """True when an operator supplied a runtime ARN and cloud credentials."""
    if os.environ.get("AGENTCORE_RUNTIME_ARN", "").strip() == "":
        return False
    access_key = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
    profile = os.environ.get("AWS_PROFILE", "").strip()
    return access_key != "" or profile != ""


def main() -> int:
    """Return 0 when smoke passes or when credentials are absent."""
    if not ready():
        print("Hosted runtime smoke skipped.")
        return 0
    root = Path(__file__).resolve().parents[1]
    document = json.loads((root / "knowledge" / "fixtures" / "support_domain.json").read_text())
    expected = order_facts_from_fixture(document, ORDER_NUMBER)
    region = os.environ.get("AWS_REGION", "").strip() or "us-east-1"
    timeout = float(os.environ.get("AGENTCORE_INVOCATION_TIMEOUT_SECONDS", "30"))
    arn = os.environ["AGENTCORE_RUNTIME_ARN"].strip()
    runner = AgentCoreRuntimeRunner(
        BotoRuntimeTransport(build_data_plane_client(region, timeout), arn),
        SessionQuota(int(os.environ.get("MAX_SESSIONS_PER_DAY", "25"))),
        timeout_seconds=timeout,
    )
    result = runner.run(
        TurnContext(
            tenant_id=HARBOR,
            customer_id=HARBOR_CUSTOMER,
            conversation_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccc0108"),
            correlation_id="smoke-runtime",
            customer_message=f"Where is {ORDER_NUMBER}?",
            history=[],
            prompt=PromptRef(id="local-support", version="1"),
        )
    )
    actual = domain_facts(result)
    if not same_order_facts(actual, expected):
        print(
            "Hosted runtime smoke failed: "
            f"status={actual.order_status} hub={actual.origin_hub} "
            f"delivery={actual.estimated_delivery_on} tools={actual.tool_names}"
        )
        return 1
    print("Hosted runtime smoke matched the seeded order facts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
