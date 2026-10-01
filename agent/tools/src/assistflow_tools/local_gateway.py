"""In-process tool gateway. It delegates to the read registry and does not use the network."""

from typing import Any

from assistflow_contracts.agent import ExecutedTool, ToolSchema
from assistflow_contracts.gateway import (
    GatewayActor,
    arguments_hash,
    is_allowlisted_tool,
    refuses_unsafe_arguments,
)

from assistflow_tools.models import ToolContext, ToolOutcome
from assistflow_tools.registry import ToolRegistry


class LocalToolGateway:
    """List and call tier-0 reads through the shared registry.

    Write tools and tier 2 calls stay blocked. An approval token in the
    arguments is not accepted.
    """

    def __init__(self, registry: ToolRegistry, *, max_executions: int = 5) -> None:
        self._registry = registry
        self._max_executions = max_executions
        self._used = 0

    def list_tools(self) -> list[ToolSchema]:
        advertised: list[ToolSchema] = []
        for tool in self._registry.advertised():
            if not is_allowlisted_tool(tool.name):
                continue
            if tool.risk_level.value != "tier0":
                continue
            description = (tool.argument_model.__doc__ or tool.name).strip().splitlines()[0]
            advertised.append(
                ToolSchema(
                    name=tool.name,
                    description=description[:400],
                    input_schema=tool.json_schema(),
                )
            )
        return advertised

    def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        actor_context: GatewayActor | None,
    ) -> ExecutedTool:
        digest = arguments_hash(name, arguments)
        if actor_context is None:
            return _denied(name, digest, "missing_actor", "A tenant context is required.")
        if not is_allowlisted_tool(name):
            return _denied(name, digest, "tool_denied", "That action is not available.", tier3=True)
        if refuses_unsafe_arguments(arguments):
            return _denied(name, digest, "invalid_arguments", "The arguments are not allowed.")
        registered = self._registry.lookup(name)
        if registered is None or registered.risk_level.value != "tier0":
            return _denied(name, digest, "tool_denied", "That action is not available.", tier3=True)
        outcome = self._registry.execute(
            name,
            arguments,
            ToolContext(
                tenant_id=actor_context.tenant_id,
                customer_id=actor_context.customer_id,
                actor_type=actor_context.actor_type,
                correlation_id=actor_context.correlation_id,
                conversation_id=actor_context.conversation_id,
            ),
            executions_used=self._used,
            max_executions=self._max_executions,
        )
        self._used += 1
        return _executed(outcome)


def _executed(outcome: ToolOutcome) -> ExecutedTool:
    return ExecutedTool(
        name=outcome.name,
        status=outcome.status.value,
        error_code=outcome.error_code,
        summary=outcome.summary,
        body=outcome.body,
        risk_level=outcome.risk_level.value,
        arguments_hash=outcome.arguments_hash,
    )


def _denied(
    name: str,
    digest: str,
    code: str,
    summary: str,
    *,
    tier3: bool = False,
) -> ExecutedTool:
    return ExecutedTool(
        name=name,
        status="blocked",
        error_code=code,
        summary=summary[:240],
        body=None,
        risk_level="tier3" if tier3 else "tier0",
        arguments_hash=digest,
    )
