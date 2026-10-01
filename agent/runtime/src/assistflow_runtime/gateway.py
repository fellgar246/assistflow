"""Tool gateway port. The hosted client is built only when the operator enables it.

Local development uses the in-process adapter and does not open a gateway connection.
A gateway failure becomes a tool result. It does not escape as an unhandled error.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

from assistflow_contracts.agent import ExecutedTool, ToolSchema
from assistflow_contracts.gateway import (
    GatewayActor,
    arguments_hash,
    is_allowlisted_tool,
    refuses_unsafe_arguments,
    sign_actor_context,
)
from pydantic import ValidationError


class GatewayTransportError(Exception):
    """The gateway call failed before a usable tool result."""


class GatewayDeniedError(Exception):
    """The gateway rejected the credential or the call."""


class GatewayTransport(Protocol):
    """One MCP operation against a hosted or fake gateway."""

    def request(
        self,
        method: str,
        params: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """Send tools/list or tools/call and return the JSON document."""


class ToolGateway(Protocol):
    """Allowlisted tools and one call. The actor comes from the server, not the model."""

    def list_tools(self) -> list[ToolSchema]:
        """Tools the model may see. Tier 3 names are omitted."""

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        actor_context: GatewayActor | None,
    ) -> ExecutedTool:
        """Run one tool. A missing actor is rejected. Failures stay inside the result."""


class UnavailableGatewayTransport:
    """Stand-in used when the hosted gateway URL is empty. It does not use the network."""

    def request(
        self,
        method: str,
        params: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        del method, params, headers
        raise GatewayTransportError("The hosted gateway is not configured.")


class UrllibGatewayTransport:
    """POST JSON-RPC to the hosted gateway. urllib is imported on the first call."""

    def __init__(self, url: str, timeout_seconds: float) -> None:
        if url.strip() == "":
            raise ValueError("A hosted gateway URL is required.")
        self._url = url
        self._timeout = timeout_seconds

    def request(
        self,
        method: str,
        params: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        import urllib.error
        import urllib.request

        payload = json.dumps(
            {"jsonrpc": "2.0", "id": "1", "method": method, "params": params}
        ).encode()
        request_headers = {
            "content-type": "application/json",
            "accept": "application/json",
        }
        request_headers.update(headers)
        request = urllib.request.Request(
            self._url,
            data=payload,
            headers=request_headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise GatewayDeniedError() from exc
            raise GatewayTransportError("The gateway rejected the call.") from exc
        except GatewayDeniedError:
            raise
        except Exception as exc:
            raise GatewayTransportError("The gateway call failed.") from exc
        parsed = json.loads(raw.decode())
        if not isinstance(parsed, dict):
            raise GatewayTransportError("The gateway response was not a document.")
        return parsed


class AgentCoreToolGateway:
    """Call the hosted gateway with tools/list and tools/call.

    Construct this only when the hosted agent is enabled. The tenant rides in a
    signed header. It is not a tool argument.
    """

    def __init__(
        self,
        transport: GatewayTransport,
        *,
        inbound_token: str,
        context_secret: str,
    ) -> None:
        self._transport = transport
        self._token = inbound_token
        self._secret = context_secret

    def list_tools(self) -> list[ToolSchema]:
        try:
            document = self._transport.request("tools/list", {}, self._auth_headers())
        except (GatewayTransportError, GatewayDeniedError):
            return []
        result = document.get("result", document)
        raw_tools = result.get("tools") if isinstance(result, dict) else None
        if not isinstance(raw_tools, list):
            return []
        advertised: list[ToolSchema] = []
        for item in raw_tools:
            parsed = _published_tool(item)
            if parsed is not None:
                advertised.append(parsed)
        return advertised

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        actor_context: GatewayActor | None,
    ) -> ExecutedTool:
        if actor_context is None:
            return _result(
                name,
                arguments,
                "blocked",
                "missing_actor",
                "A tenant context is required.",
            )
        if not is_allowlisted_tool(name):
            return _result(
                name,
                arguments,
                "blocked",
                "tool_denied",
                "That action is not available.",
            )
        if refuses_unsafe_arguments(arguments):
            return _result(
                name,
                arguments,
                "blocked",
                "invalid_arguments",
                "The arguments are not allowed.",
            )
        if self._secret.strip() == "":
            return _result(
                name,
                arguments,
                "failed",
                "gateway_unavailable",
                "The hosted gateway is not configured.",
            )
        headers = self._auth_headers()
        headers["x-actor-context"] = sign_actor_context(actor_context, self._secret)
        try:
            document = self._transport.request(
                "tools/call",
                {"name": name, "arguments": arguments},
                headers,
            )
        except GatewayDeniedError:
            return _result(name, arguments, "blocked", "denied", "The gateway denied that lookup.")
        except GatewayTransportError:
            return _result(
                name,
                arguments,
                "failed",
                "gateway_unavailable",
                "The lookup could not be completed.",
            )
        return _parse_call(name, arguments, document)

    def _auth_headers(self) -> dict[str, str]:
        if self._token.strip() == "":
            return {}
        return {"authorization": f"Bearer {self._token}"}


def build_agentcore_gateway(
    *,
    url: str,
    token: str,
    secret: str,
    timeout_seconds: float = 3.0,
) -> AgentCoreToolGateway:
    """Build the hosted client. An empty URL does not open a connection."""
    endpoint = url.strip()
    if endpoint == "":
        transport: GatewayTransport = UnavailableGatewayTransport()
    else:
        transport = UrllibGatewayTransport(endpoint, timeout_seconds)
    return AgentCoreToolGateway(transport, inbound_token=token, context_secret=secret)


def _published_tool(item: object) -> ToolSchema | None:
    if not isinstance(item, dict):
        return None
    name = item.get("name")
    if not isinstance(name, str) or not is_allowlisted_tool(name):
        return None
    description = item.get("description")
    text = description.strip() if isinstance(description, str) and description.strip() else name
    schema = item.get("inputSchema")
    if not isinstance(schema, dict):
        schema = item.get("input_schema")
    if not isinstance(schema, dict):
        schema = {"type": "object"}
    return ToolSchema(name=name, description=text[:400], input_schema=schema)


def _parse_call(name: str, arguments: dict[str, Any], document: dict[str, Any]) -> ExecutedTool:
    if "error" in document:
        return _result(name, arguments, "blocked", "denied", "The gateway denied that lookup.")
    result = document.get("result")
    if not isinstance(result, dict):
        return _result(
            name,
            arguments,
            "failed",
            "gateway_unavailable",
            "The gateway response was not a tool result.",
        )
    if result.get("isError") is True:
        return _result(
            name,
            arguments,
            "failed",
            "gateway_unavailable",
            "The gateway could not run that lookup.",
        )
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if not isinstance(text, str):
                continue
            parsed = _load_tool(text)
            if parsed is not None:
                return _without_failed_body(parsed)
        return _result(
            name,
            arguments,
            "failed",
            "gateway_unavailable",
            "The gateway response was not a tool result.",
        )
    if "status" in result and "name" in result:
        parsed = _load_tool_document(result)
        if parsed is not None:
            return _without_failed_body(parsed)
    return _result(
        name,
        arguments,
        "failed",
        "gateway_unavailable",
        "The gateway response was not a tool result.",
    )


def _load_tool(text: str) -> ExecutedTool | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return _load_tool_document(parsed)


def _load_tool_document(document: dict[str, Any]) -> ExecutedTool | None:
    try:
        return ExecutedTool.model_validate(document)
    except ValidationError:
        return None


def _without_failed_body(tool: ExecutedTool) -> ExecutedTool:
    if tool.status == "succeeded":
        return tool
    return tool.model_copy(update={"body": None})


def _result(
    name: str,
    arguments: dict[str, Any],
    status: str,
    error_code: str,
    summary: str,
) -> ExecutedTool:
    return ExecutedTool(
        name=name,
        status=status,
        error_code=error_code,
        summary=summary[:240],
        body=None,
        risk_level="tier3" if error_code == "tool_denied" else "tier0",
        arguments_hash=arguments_hash(name, arguments),
    )
