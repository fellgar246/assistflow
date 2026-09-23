# ADR 0001: The agent proposes and the application authorizes

## Status

Accepted

## Context

A support agent needs to look up orders and, later, request changes such as a refund or an address update. If the model can call business code directly, a fluent reply becomes an authorization decision. Retrieved policy text has the same problem: it can describe a rule without being allowed to apply it.

## Decision

The model is not the authorization layer. A tool call follows this sequence and no shorter path:

1. The agent proposes a tool call.
2. The application validates the tool schema.
3. The application checks identity and tenant.
4. The application checks business policy.
5. The application classifies risk.
6. If the risk tier requires approval, execution waits for a valid, unexpired approval bound to the hash of the tool name plus the canonical arguments.
7. The application runs an idempotent command in the business service.
8. The application records an audit event.

Model text must not mutate orders, shipments, refunds, addresses, or accounts. Retrieved policy prose must not authorize a write by itself.

## Consequences

- Domain services stay free of model SDKs.
- Every write has an application owner, an idempotency key, and an audit event.
- A convincing model response is not a completed transaction. The UI must wait for the application result.
