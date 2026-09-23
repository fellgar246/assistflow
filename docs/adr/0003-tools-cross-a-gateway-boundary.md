# ADR 0003: Tools cross a gateway boundary

## Status

Accepted

## Context

The agent needs tools for orders, shipments, returns, refunds, and tickets. If those tools are function calls inside the model process, the application cannot reliably enforce schema, tenant, and policy checks. A hosted tool gateway and a local tool gateway would also drift apart.

## Decision

Every tool call crosses a gateway boundary owned by the application. The agent proposes the call. The gateway is the only path into a business command. It validates the schema, the caller, the tenant, and policy before the command runs.

The local gateway and any later hosted gateway implement that same boundary. Domain services do not import a model SDK, and the agent does not write business tables directly.

## Consequences

- Tool contracts live in typed schemas, not in prompt prose.
- Swapping a local gateway for a hosted one does not change authorization.
- A new tool is unavailable until the gateway publishes it. The model cannot invent a callable side door.
