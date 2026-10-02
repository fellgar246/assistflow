"""Validate a proposed tool call, then run the matching handler.

Write tools are not retried. Tier 2 mutation is reached only through apply_approved.
"""

import contextvars
import threading
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from assistflow_tools.approval import ApplicationApproval
from assistflow_tools.hashing import arguments_hash
from assistflow_tools.models import (
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    READ_TIMEOUT_RETRIES,
    SUMMARY_LIMIT,
    AddTicketNoteArgs,
    CheckEligibilityArgs,
    CreateRefundRequestArgs,
    CreateReturnRequestArgs,
    CreateTicketArgs,
    GetCustomerProfileArgs,
    GetOrderArgs,
    GetShipmentArgs,
    GetTicketArgs,
    RequestHumanEscalationArgs,
    RiskLevel,
    SearchSupportPolicyArgs,
    ToolContext,
    ToolError,
    ToolOutcome,
    ToolRefusal,
    ToolStatus,
    ToolTimeoutError,
    UpdateShippingAddressArgs,
)

Handler = Callable[[ToolContext, Any], dict[str, Any]]


class _ToolSpec:
    def __init__(
        self, argument_model: type[BaseModel], risk_level: RiskLevel, retries: int
    ) -> None:
        self.argument_model = argument_model
        self.risk_level = risk_level
        self.retries = retries


_CATALOG: dict[str, _ToolSpec] = {
    "get_order": _ToolSpec(GetOrderArgs, RiskLevel.TIER0, READ_TIMEOUT_RETRIES),
    "get_shipment": _ToolSpec(GetShipmentArgs, RiskLevel.TIER0, READ_TIMEOUT_RETRIES),
    "get_customer_profile": _ToolSpec(
        GetCustomerProfileArgs, RiskLevel.TIER0, READ_TIMEOUT_RETRIES
    ),
    "get_ticket": _ToolSpec(GetTicketArgs, RiskLevel.TIER0, READ_TIMEOUT_RETRIES),
    "search_support_policy": _ToolSpec(
        SearchSupportPolicyArgs, RiskLevel.TIER0, READ_TIMEOUT_RETRIES
    ),
    "check_address_change_eligibility": _ToolSpec(
        CheckEligibilityArgs, RiskLevel.TIER0, READ_TIMEOUT_RETRIES
    ),
    "check_return_eligibility": _ToolSpec(
        CheckEligibilityArgs, RiskLevel.TIER0, READ_TIMEOUT_RETRIES
    ),
    "check_refund_eligibility": _ToolSpec(
        CheckEligibilityArgs, RiskLevel.TIER0, READ_TIMEOUT_RETRIES
    ),
    "create_ticket": _ToolSpec(CreateTicketArgs, RiskLevel.TIER1, 0),
    "add_ticket_note": _ToolSpec(AddTicketNoteArgs, RiskLevel.TIER1, 0),
    "request_human_escalation": _ToolSpec(RequestHumanEscalationArgs, RiskLevel.TIER1, 0),
    "update_shipping_address": _ToolSpec(UpdateShippingAddressArgs, RiskLevel.TIER2, 0),
    "create_return_request": _ToolSpec(CreateReturnRequestArgs, RiskLevel.TIER2, 0),
    "create_refund_request": _ToolSpec(CreateRefundRequestArgs, RiskLevel.TIER2, 0),
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

    def __init__(
        self,
        tools: dict[str, RegisteredTool],
        approved: dict[str, Handler] | None = None,
    ) -> None:
        self._tools = tools
        self._approved = {} if approved is None else approved

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

    def apply_approved(
        self,
        name: str,
        arguments: dict[str, Any],
        context: ToolContext,
        approval: ApplicationApproval,
    ) -> ToolOutcome:
        """Run a tier 2 mutation. The agent loop does not call this method."""
        digest = arguments_hash(name, arguments)
        if not isinstance(approval, ApplicationApproval) or not approval.granted:
            return ToolOutcome(
                name=name,
                status=ToolStatus.PENDING_APPROVAL,
                risk_level=RiskLevel.TIER2,
                arguments_hash=digest,
                summary=_clip("This change is waiting for approval."),
                error_code="pending_approval",
            )
        tool = self._tools.get(name)
        approved = self._approved.get(name)
        if tool is None or approved is None or tool.risk_level is not RiskLevel.TIER2:
            return _blocked(name, digest, "tool_denied", "That action is not available.")
        try:
            parsed = tool.argument_model.model_validate(arguments)
        except ValidationError:
            return _failed(
                name,
                RiskLevel.TIER2,
                digest,
                "validation_error",
                "The arguments are invalid.",
            )
        granted = RegisteredTool(
            name,
            tool.argument_model,
            approved,
            risk_level=RiskLevel.TIER2,
            timeout_seconds=tool.timeout_seconds,
            timeout_retries=0,
        )
        return _run(granted, parsed, context, digest)


def build_registry(
    handlers: dict[str, Handler],
    *,
    approved: dict[str, Handler] | None = None,
    timeout_seconds: float = DEFAULT_TOOL_TIMEOUT_SECONDS,
    timeout_retries: int = READ_TIMEOUT_RETRIES,
) -> ToolRegistry:
    """Register tools that have a handler. Writes are not retried after a timeout."""
    tools: dict[str, RegisteredTool] = {}
    for name, spec in _CATALOG.items():
        handler = handlers.get(name)
        if handler is None:
            continue
        retries = timeout_retries if spec.risk_level is RiskLevel.TIER0 else 0
        tools[name] = RegisteredTool(
            name,
            spec.argument_model,
            handler,
            risk_level=spec.risk_level,
            timeout_seconds=timeout_seconds,
            timeout_retries=retries,
        )
    granted = {} if approved is None else approved
    selected = {name: handler for name, handler in granted.items() if name in tools}
    return ToolRegistry(tools, selected)


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
            timed_out = (
                "The lookup timed out."
                if tool.risk_level is RiskLevel.TIER0
                else "The request timed out."
            )
            return _failed(
                tool.name,
                tool.risk_level,
                digest,
                "timeout",
                timed_out,
                attempts,
            )
        except ToolRefusal as exc:
            return ToolOutcome(
                name=tool.name,
                status=exc.status,
                risk_level=tool.risk_level,
                arguments_hash=digest,
                summary=_clip(exc.summary),
                body=exc.body,
                error_code=exc.code,
                attempts=attempts,
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
    ctx = contextvars.copy_context()

    def target() -> None:
        try:
            outcome["value"] = handler(context, arguments)
        except Exception as exc:
            outcome["error"] = exc
        finally:
            outcome["done"] = True

    thread = threading.Thread(target=ctx.run, args=(target,), daemon=True)
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
