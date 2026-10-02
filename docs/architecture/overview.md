# Architecture

AssistFlow separates a proposal from an authorized change. The model may suggest a next step. Only application code can read or change customer data, and only after the checks below succeed.

## Request path

1. The agent proposes a tool call.
2. The application validates the tool schema.
3. The application checks identity and tenant. The tenant and role come from the verified access token, not from the request body.
4. The application checks business policy.
5. The application classifies risk.
6. If that risk tier requires approval, execution waits for a valid, unexpired approval bound to the exact tool name and canonical arguments.
7. The application runs an idempotent command in the business service.
8. The application records an audit event.

Creating a ticket, escalating a conversation, consuming an approval, and resolving a conversation also store an outbox row in that same transaction. The response returns before any consumer runs. Publishing happens after the commit. A publish failure is logged and the row stays for a later attempt. The business change stays committed. Locally an in-process queue drains the row on a background task. The same handlers write an in-app notice, a fan-out audit row, a short summary when a conversation resolves, and a marker on a configured fraction of resolved conversations for later evaluation. A second delivery of the same event id does not repeat those writes. A summary failure leaves the conversation resolved. The notice email is a log line. An EventBridge or SQS client is constructed only when AWS and async workers are both enabled. `LOCAL_ONLY_MODE=true` forces the in-process queue. Terraform leaves the queue, the bus, and the consumer uncreated until `enable_async_workers` is true.

Model text does not mutate orders, shipments, refunds, addresses, or accounts. Retrieved policy prose does not authorize a write by itself. The same allowlist applies to the local gateway and the hosted gateway. A document chunk is wrapped before the model sees it, and a verbatim copy of the prompt is not returned to the customer.

Bearer tokens, AWS access-key ids, and card numbers are redacted before they are stored or logged. An optional hosted filter runs only when the hosted model and `GUARDRAILS_ENABLED` are both on. It checks input before the tool loop and checks the reply before it is trusted. If that filter errors, the turn stops. It does not skip the check. A grounding result from that filter does not replace facts that came from tools.

Tool calls cross a gateway boundary. Domain services do not accept a shortcut from prompt text or from a model SDK. A local gateway and a hosted gateway implement the same checks. The local gateway is the default and does not open a network connection. The hosted gateway is created only when the hosted runtime is enabled. The runtime authenticates to it, and the gateway calls the tool function with its own role. The tenant id is signed by the application. The model cannot pass it as a trusted argument.

Low-risk writes — opening a ticket, adding a ticket note, and escalating a conversation — require an idempotency key. Replaying that key with the same arguments returns the original result and does not repeat the effect. A different payload for the same key is a conflict. Sensitive writes — a shipping address, a return, and a refund request — wait for the customer. An eligible proposal stores an approval and a tool execution together, expires 15 minutes after it is requested, and is bound to the hash of the tool name plus the canonical arguments. The chat shows the difference and does not claim the change already happened. Confirm and cancel are conversation routes. They accept the approval id and reload the stored arguments. A new address in the request body is rejected. Confirm checks that the approval is pending and unexpired, checks the hash again, runs the idempotent command, and marks the approval consumed in that same transaction. A second confirm returns the original outcome. Reject and expiry leave business rows unchanged. Reading an approval past its expiry marks it expired. The model cannot supply the approval. A refund request is never marked paid and never stores a payment instrument. Write calls are not retried on their own; a client retries by sending the same idempotency key.

## Local by default

The default execution profile is local:

- the web app, the API, and PostgreSQL run on the developer machine;
- AWS, the hosted agent, the hosted model, managed retrieval, long-term memory, and async workers are off;
- cloud adapters stay behind interfaces and are not imported while AWS is disabled;
- the in-process assistant proposes tool calls, writes a trace, and does not import a hosted-model SDK.

`LOCAL_ONLY_MODE=true` is a hard stop. It turns those hosted flags off and forces the local retrieval provider even when the rest of the environment asks for an AWS provider. The API still serves health checks.

Retrieval uses one port. The local index is the default. An S3 provider scores the same published files after an operator syncs them into a private bucket. A managed knowledge base stays behind its own flag and requires a tenant metadata filter or a base per tenant. The turn loop does not construct either client.

The same turn contract can run in-process or in a hosted runtime. The hosted path is off unless the operator enables it and deploys it with a separate command. Pull-request checks do not create that runtime. A hosted session id is the conversation id. The application reserves the daily session before the remote call.

## Memory

A turn always receives the newest bounded slice of the conversation. That transcript is not a memory client.

Session memory is a separate flag. When `SHORT_TERM_MEMORY_ENABLED=true`, the application stores the last order id and the last shipment status for that conversation. Those facts expire within `MAX_SESSION_MINUTES` and the conversation cannot hold more than `MAX_MEMORY_EVENTS_PER_SESSION` events. They are passed to the assistant as data, beside the transcript. A remembered order id is still checked against the tenant when a tool runs. With the flag off, no session store is read or written. If the order number is still inside the history window, the follow-up can use that text. If the window no longer has it, the assistant asks which order.

Long-term memory is off unless `LONG_TERM_MEMORY_ENABLED=true`. It stores only `preferred_language` (`en` or `es`) and `preferred_contact_channel` (`web` or `email`). Each row keeps a purpose, the tenant and customer who own it, and a retention deadline 365 days after it was saved. A payment number, a password, or any other key is rejected and nothing is stored. `GET /preferences` and `DELETE /preferences` use the current customer. Another tenant cannot read or delete those rows. With the flag off, a turn does not read or write the preference store, and the routes are not available.

Values are redacted before they are written. A hosted memory client is constructed only when `AGENTCORE_ENABLED=true` and the matching memory flag is on. Otherwise the local tables are used, or nothing is constructed.

## Limits

Execution limits live in configuration, not in prompts. Exceeding a limit stops the turn. It does not retry without a bound. The local profile still enforces step, tool, and retrieval caps so the same guards are tested without a cloud account.

## Dependencies

- `apps/web` talks to the API over HTTP. It does not import agent SDKs or business services.
- `apps/api` orchestrates use cases and depends on ports.
- `services/` implement commerce and support rules. They do not import a model SDK.
- `agent/` proposes actions through the tool gateway. It does not write business tables directly. The runtime package does not import commerce services.
- `packages/contracts` holds shared schemas and performs no I/O.
