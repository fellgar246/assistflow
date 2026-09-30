# ADR 0009: Business reads use the tool gateway

## Status

Accepted

## Context

The hosted assistant has to read orders, shipments, profiles, tickets, and published help without calling those services from the model process. A local run has to exercise the same list and call operations without an AWS account. The tenant has to come from the server session. The model must not be able to mint it.

## Decision

Tool calls cross one gateway port: list the allowlisted tools, then call one tool with an actor context. The local adapter delegates to the in-process read registry and makes no network call. The hosted client is constructed only when the hosted-agent flag is on. It speaks `tools/list` and `tools/call`.

The first hosted tools are the tier-0 reads, including policy search. Write tools are not published. A tier 2 name is blocked, and an approval token in the arguments is not accepted.

Inbound IAM authenticates the runtime. The gateway's own role invokes only the read-tool function. The customer tenant rides in a signed context. A bad credential is rejected before a handler runs. SQL, shell, and URL arguments are refused. A gateway failure is stored as a failed tool call. The assistant does not fill in the order from model text.

The gateway module stays off unless the hosted runtime is enabled. Pull-request checks do not deploy it. An operator smoke for list and call skips when the gateway URL or credentials are missing.

Revalidate current gateway pricing before apply. Prices are not hard-coded.

## Consequences

- Local tests use the in-process adapter.
- The hosted runtime package does not import the commerce services. Reads leave through the gateway client.
- The gateway execution policy names the tool function. It does not grant a wildcard action on all resources.
- Operators enable the gateway with the hosted runtime, after checking current pricing.
