# Architecture

AssistFlow separates a proposal from an authorized change. The model may suggest a next step. Only application code can read or change customer data, and only after the checks below succeed.

## Request path

1. The agent proposes a tool call.
2. The application validates the tool schema.
3. The application checks identity and tenant.
4. The application checks business policy.
5. The application classifies risk.
6. If that risk tier requires approval, execution waits for a valid, unexpired approval bound to the exact tool name and canonical arguments.
7. The application runs an idempotent command in the business service.
8. The application records an audit event.

Model text does not mutate orders, shipments, refunds, addresses, or accounts. Retrieved policy prose does not authorize a write by itself.

Tool calls cross a gateway boundary. Domain services do not accept a shortcut from prompt text or from a model SDK. A local gateway and a hosted gateway implement the same checks.

## Local by default

The default execution profile is local:

- the web app, the API, and PostgreSQL run on the developer machine;
- AWS, the hosted agent, the hosted model, managed retrieval, and long-term memory are off;
- cloud adapters stay behind interfaces and are not imported while AWS is disabled;
- the in-process assistant proposes tool calls, writes a trace, and does not import a hosted-model SDK.

`LOCAL_ONLY_MODE=true` is a hard stop. It turns those hosted flags off even when the rest of the environment asks for them. The API still serves health checks.

## Limits

Execution limits live in configuration, not in prompts. Exceeding a limit stops the turn. It does not retry without a bound. The local profile still enforces step, tool, and retrieval caps so the same guards are tested without a cloud account.

## Dependencies

- `apps/web` talks to the API over HTTP. It does not import agent SDKs or business services.
- `apps/api` orchestrates use cases and depends on ports.
- `services/` implement commerce and support rules. They do not import a model SDK.
- `agent/` proposes actions through the tool registry. It does not write business tables directly.
- `packages/contracts` holds shared schemas and performs no I/O.
