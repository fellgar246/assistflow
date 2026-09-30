"""Gateway target for the read tools.

Inbound credentials are checked before a handler runs. The tenant comes from
the signed actor context. SQL, shell, and URL arguments are refused.
"""

import os
from collections.abc import Mapping
from typing import Any

from assistflow_contracts.gateway import (
    credentials_match,
    verify_actor_context,
)

from assistflow_knowledge.managed import ManagedRetrievalClient
from assistflow_knowledge.object_store import ObjectStore
from assistflow_tools.handlers import service_handlers
from assistflow_tools.local_gateway import LocalToolGateway
from assistflow_tools.registry import ToolRegistry, build_registry


def inbound_authorized(event: Mapping[str, Any], expected_token: str) -> bool:
    """True when the presented credential matches the runtime token."""
    return credentials_match(presented_credential(event), expected_token)


def dispatch_tool_call(
    event: Mapping[str, Any],
    registry: ToolRegistry,
    *,
    expected_token: str,
    context_secret: str,
) -> dict[str, Any]:
    """Authenticate, then run one read. A bad credential never reaches the registry."""
    if not inbound_authorized(event, expected_token):
        return {"ok": False, "error": "unauthorized"}
    raw_actor = _actor_token(event)
    actor = verify_actor_context(raw_actor, context_secret) if raw_actor is not None else None
    name = event.get("name")
    tool_name = name if isinstance(name, str) and name.strip() else "unknown"
    arguments = event.get("arguments")
    payload = arguments if isinstance(arguments, dict) else {}
    outcome = LocalToolGateway(registry).call_tool(tool_name, payload, actor)
    return {"ok": True, "tool": outcome.model_dump(mode="json")}


def lambda_handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """AWS entry for the read-tool function. A bad credential skips the database."""
    del context
    expected = os.environ.get("GATEWAY_INBOUND_TOKEN", "")
    if not inbound_authorized(event, expected):
        return {"ok": False, "error": "unauthorized"}
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url == "":
        return {"ok": False, "error": "unavailable"}
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from assistflow_knowledge.selection import build_retriever_from_environ

    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            registry = build_registry(
                service_handlers(
                    session,
                    retriever=build_retriever_from_environ(
                        session,
                        object_store=_object_store(),
                        managed_client=_managed_client(),
                    ),
                )
            )
            return dispatch_tool_call(
                event,
                registry,
                expected_token=expected,
                context_secret=os.environ.get("AGENTCORE_ACTOR_CONTEXT_SECRET", ""),
            )
    finally:
        engine.dispose()


def _object_store() -> ObjectStore | None:
    """Build an S3 client only when this process is configured for that provider."""
    if os.environ.get("LOCAL_ONLY_MODE", "").strip().lower() in {"1", "true", "yes", "on"}:
        return None
    if os.environ.get("RAG_PROVIDER", "local").strip().lower() != "s3":
        return None
    from assistflow_tools.aws_retrieval import s3_store

    region = os.environ.get("AWS_REGION", "").strip() or "us-east-1"
    return s3_store(region)


def _managed_client() -> ManagedRetrievalClient | None:
    """Build a managed retrieve client only when that provider is selected."""
    if os.environ.get("LOCAL_ONLY_MODE", "").strip().lower() in {"1", "true", "yes", "on"}:
        return None
    if os.environ.get("RAG_PROVIDER", "local").strip().lower() != "managed":
        return None
    from assistflow_tools.aws_retrieval import managed_retrieve_client

    region = os.environ.get("AWS_REGION", "").strip() or "us-east-1"
    return managed_retrieve_client(region)


def presented_credential(event: Mapping[str, Any]) -> str:
    """Read a bearer token from the event. The value is not logged."""
    headers = event.get("headers")
    if isinstance(headers, dict):
        for key in ("authorization", "Authorization"):
            value = headers.get(key)
            if isinstance(value, str):
                return _strip_bearer(value)
    for key in ("authorization", "Authorization"):
        value = event.get(key)
        if isinstance(value, str):
            return _strip_bearer(value)
    return ""


def _actor_token(event: Mapping[str, Any]) -> str | None:
    direct = event.get("actor_context")
    if isinstance(direct, str) and direct.strip():
        return direct
    headers = event.get("headers")
    if isinstance(headers, dict):
        for key in ("x-actor-context", "X-Actor-Context"):
            value = headers.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return None


def _strip_bearer(value: str) -> str:
    prefix = "bearer "
    if value.lower().startswith(prefix):
        return value[len(prefix) :].strip()
    return value.strip()
