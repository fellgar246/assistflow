"""Tool-gateway actor context. This module performs no input or output.

The model cannot mint a tenant. Callers pass a server-side actor, and the
hosted path signs that actor with a secret the model does not have.
"""

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

READ_TOOL_NAMES = frozenset(
    {
        "get_order",
        "get_shipment",
        "get_customer_profile",
        "get_ticket",
        "search_support_policy",
    }
)

TIER3_TOOL_NAMES = frozenset(
    {
        "issue_payment",
        "delete_customer_account",
        "override_refund_policy",
        "change_order_total",
    }
)


def is_allowlisted_tool(name: str) -> bool:
    """True when the name is a tier-0 read the application may execute."""
    return name in READ_TOOL_NAMES and name not in TIER3_TOOL_NAMES


_UNTRUSTED_KEYS = frozenset(
    {
        "tenant_id",
        "role",
        "approval_token",
        "actor_type",
        "sql",
        "shell",
        "command",
        "url",
        "uri",
        "endpoint",
        "script",
    }
)

_SQL_STATEMENT = re.compile(
    r"(?is)^\s*(select|insert|update|delete|drop|alter)\b.+\b(from|into|table|set)\b"
)
_SHELL = re.compile(r"(?is)^\s*(sudo\s+|rm\s+|curl\s+|wget\s+|bash\s+|sh\s+|\$\()")


class GatewayActor(BaseModel):
    """Identity taken from the server session. Tool arguments cannot replace it."""

    model_config = ConfigDict(frozen=True)

    tenant_id: UUID
    customer_id: UUID
    actor_type: str = Field(min_length=1, max_length=32)
    correlation_id: str = Field(min_length=1, max_length=200)
    conversation_id: UUID


def arguments_hash(tool_name: str, arguments: Mapping[str, object]) -> str:
    """Hash a tool name with its canonical arguments. Key order does not matter."""
    canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=_encode)
    payload = f"{tool_name}{canonical}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def refuses_unsafe_arguments(arguments: Mapping[str, Any]) -> bool:
    """Reject SQL, shell, URL, and identity fields the model must not supply."""
    for key, value in arguments.items():
        if str(key).lower() in _UNTRUSTED_KEYS:
            return True
        if not isinstance(value, str):
            continue
        if "://" in value:
            return True
        if _SQL_STATEMENT.search(value) or _SHELL.search(value):
            return True
    return False


def sign_actor_context(actor: GatewayActor, secret: str) -> str:
    """Sign the actor. An empty secret is refused so the token cannot be forged."""
    if secret.strip() == "":
        raise ValueError("An actor-context secret is required.")
    payload = _canonical_actor(actor)
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"{payload.decode('utf-8')}.{digest}"


def verify_actor_context(token: str, secret: str) -> GatewayActor | None:
    """Return the actor only when the signature matches. Otherwise return none."""
    if secret.strip() == "" or "." not in token:
        return None
    payload, _, digest = token.rpartition(".")
    if payload == "" or digest == "":
        return None
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, digest):
        return None
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    try:
        return GatewayActor.model_validate(parsed)
    except ValidationError:
        return None


def credentials_match(provided: str, expected: str) -> bool:
    """Compare inbound credentials without short-circuiting on the first byte."""
    if provided.strip() == "" or expected.strip() == "":
        return False
    return hmac.compare_digest(provided.strip().encode("utf-8"), expected.strip().encode("utf-8"))


def _canonical_actor(actor: GatewayActor) -> bytes:
    return json.dumps(
        actor.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _encode(value: object) -> str:
    return str(value)
