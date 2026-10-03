"""Health and seeded-order probe for the dev API.

PostgreSQL remains the system of record. This function does not read it.
"""

import json
from typing import Any

SEEDED_ORDER = {
    "order_number": "ORD-10482",
    "status": "in_transit",
    "origin_hub": "DFW",
}


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    """Return health, or the seeded order the local fixture uses."""
    route = str(event.get("rawPath") or event.get("path") or "")
    if route.endswith("/orders/ORD-10482"):
        body: dict[str, str] = SEEDED_ORDER
    else:
        body = {"status": "healthy"}
    return {
        "statusCode": 200,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }
