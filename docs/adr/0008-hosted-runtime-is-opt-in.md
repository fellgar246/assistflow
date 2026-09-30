# ADR 0008: The hosted runtime is opt-in

## Status

Accepted

## Context

The assistant has to be able to run on a developer machine and, when an operator chooses, inside a hosted agent runtime. Those two hosts need the same turn contract so an order-status answer is comparable. A pull request must not create the hosted runtime or call its control plane.

## Decision

`AgentRunner` stays the port. The API uses an in-process runner by default. When the hosted-agent flag is on, a runtime runner sends the turn to the hosted runtime and maps the response back.

The hosted process boots the same loop and the same tool registry. It does not add a second authorization path. The runtime session id is the conversation id. It is never a customer email.

A hosted session is reserved before the remote call. A failed call does not return that slot. A transport error is retried once. An invocation that exceeds the configured timeout fails the turn and leaves the conversation usable.

The runtime module is off unless `enable_agentcore` is true. Applying the dev stack without that flag creates no runtime resource. Packaging and apply are an operator command. Pull-request checks do not run them.

A successful hosted call stores the runtime invocation id and the call duration on the turn trace.

Revalidate current runtime pricing before apply. Prices are not hard-coded.

## Consequences

- Local tests run with the hosted client unbuilt.
- Two conversations receive two session ids, and each tool call stays inside its tenant.
- The daily session cap stops a new hosted session before the remote call.
- Operators deploy the runtime explicitly, after checking current pricing.
