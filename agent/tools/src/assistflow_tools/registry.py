"""Validate a proposed tool call, then run the matching read handler."""

import threading
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from assistflow_tools.hashing import arguments_hash
from assistflow_tools.models import (
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    READ_TIMEOUT_RETRIES,
    SUMMARY_LIMIT,
    GetCustomerProfileArgs,
    GetOrderArgs,
    GetShipmentArgs,
    GetTicketArgs,
    RiskLevel,
    SearchSupportPolicyArgs,
    ToolContext,
    ToolError,
    ToolOutcome,
    ToolStatus,
    ToolTimeoutError,
)

Handler = Callable[[ToolContext, Any], dict[str, Any]]

_ARGUMENT_MODELS: dict[str, type[BaseModel]] = {
    "get_order": GetOrderArgs,
    "get_shipment": GetShipmentArgs,
    "get_customer_profile": GetCustomerProfileArgs,
    "get_ticket": GetTicketArgs,
    "search_support_policy": SearchSupportPolicyArgs,
}


class RegisteredTool:
    """Schema, risk, timeout, and handler for one allowlisted name."""

    def __init__(
        self,
        name: str,
        argument_model: type[BaseModel],
        handler: Handler,
        *,
        risk_level: RiskLevel = RiskLevel.TIER0,
        timeout_seconds: float = DEFAULT_TOOL_TIMEOUT_SECONDS,
        timeout_retries: int = READ_TIMEOUT_RETRIES,
    ) -> None:
        self.name = name
        self.argument_model = argument_model
        self.handler = handler
        self.risk_level = risk_level
        self.timeout_seconds = timeout_seconds
        self.timeout_retries = timeout_retries

    def json_schema(self) -> dict[str, Any]:
        return self.argument_model.model_json_schema()


class ToolRegistry:
    """Run an allowlisted tool. Unknown names and bad arguments never call a handler."""

    def __init__(self, tools: dict[str, RegisteredTool]) -> None:
        self._tools = tools

    def names(self) -> frozenset[str]:
        return frozenset(self._tools)

    def lookup(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def advertised(self) -> list[RegisteredTool]:
        """Tools the model may see. Tier 3 names are never included."""
        return [tool for tool in self._tools.values() if tool.risk_level is not RiskLevel.TIER3]

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: ToolContext,
        *,
        executions_used: int = 0,
        max_executions: int = 5,
    ) -> ToolOutcome:
        """Validate, authorize, and run one call. The cap applies to real execution."""
        digest = arguments_hash(name, arguments)
        if executions_used >= max_executions:
            return _blocked(name, digest, "tool_limit", "This request used too many lookups.")
        tool = self._tools.get(name)
        if tool is None:
            return _blocked(name, digest, "tool_denied", "That action is not available.")
        try:
            parsed = tool.argument_model.model_validate(arguments)
        except ValidationError:
            return _failed(
                name,
                tool.risk_level,
                digest,
                "validation_error",
                "The arguments are invalid.",
            )
        if name == "get_customer_profile" and context.actor_type == "customer":
            requested = getattr(parsed, "customer_id", None)
            if requested != context.customer_id:
                return _blocked(name, digest, "denied", "That profile is not available.")
        return _run(tool, parsed, context, digest)


def build_registry(
    handlers: dict[str, Handler],
    *,
    timeout_seconds: float = DEFAULT_TOOL_TIMEOUT_SECONDS,
    timeout_retries: int = READ_TIMEOUT_RETRIES,
) -> ToolRegistry:
    """Register the read tools that have a handler."""
    tools: dict[str, RegisteredTool] = {}
    for name, model in _ARGUMENT_MODELS.items():
        handler = handlers.get(name)
        if handler is None:
            continue
        tools[name] = RegisteredTool(
            name,
            model,
            handler,
            timeout_seconds=timeout_seconds,
            timeout_retries=timeout_retries,
        )
    return ToolRegistry(tools)


def _run(
    tool: RegisteredTool, arguments: BaseModel, context: ToolContext, digest: str
) -> ToolOutcome:
    attempts = 0
    while True:
        attempts += 1
        try:
            body = _invoke(tool.handler, context, arguments, tool.timeout_seconds)
        except ToolTimeoutError:
            if attempts <= tool.timeout_retries:
                continue
            return _failed(
                tool.name,
                tool.risk_level,
                digest,
                "timeout",
                "The lookup timed out.",
                attempts,
            )
        except ToolError as exc:
            status = ToolStatus.BLOCKED if exc.code == "denied" else ToolStatus.FAILED
            return ToolOutcome(
                name=tool.name,
                status=status,
                risk_level=tool.risk_level,
                arguments_hash=digest,
                summary=_clip(exc.summary),
                body=None,
                error_code=exc.code,
                attempts=attempts,
            )
        return ToolOutcome(
            name=tool.name,
            status=ToolStatus.SUCCEEDED,
            risk_level=tool.risk_level,
            arguments_hash=digest,
            summary=_clip(f"{tool.name} succeeded"),
            body=body,
            attempts=attempts,
        )


def _invoke(
    handler: Handler,
    context: ToolContext,
    arguments: BaseModel,
    timeout_seconds: float,
) -> dict[str, Any]:
    outcome: dict[str, object] = {}

    def target() -> None:
        try:
            outcome["value"] = handler(context, arguments)
        except Exception as exc:
            outcome["error"] = exc
        finally:
            outcome["done"] = True

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    if "done" not in outcome:
        raise ToolTimeoutError()
    error = outcome.get("error")
    if isinstance(error, Exception):
        raise error
    value = outcome.get("value")
    if not isinstance(value, dict):
        raise ToolError("internal_error", "The lookup failed.")
    return value


def _blocked(name: str, digest: str, code: str, summary: str) -> ToolOutcome:
    return ToolOutcome(
        name=name,
        status=ToolStatus.BLOCKED,
        risk_level=RiskLevel.TIER3 if code == "tool_denied" else RiskLevel.TIER0,
        arguments_hash=digest,
        summary=_clip(summary),
        error_code=code,
    )


def _failed(
    name: str,
    risk_level: RiskLevel,
    digest: str,
    code: str,
    summary: str,
    attempts: int = 1,
) -> ToolOutcome:
    return ToolOutcome(
        name=name,
        status=ToolStatus.FAILED,
        risk_level=risk_level,
        arguments_hash=digest,
        summary=_clip(summary),
        error_code=code,
        attempts=attempts,
    )


def _clip(summary: str) -> str:
    return summary[:SUMMARY_LIMIT]
