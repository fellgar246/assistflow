# ADR 0004: Sensitive writes need human approval

## Status

Accepted

## Context

Some support actions are reversible lookups. Others change money, delivery, or identity: refunds, return outcomes, shipping addresses, and account details. Those writes are too sensitive to run because a model proposed them.

## Decision

Sensitive writes wait for a person. An approval authorizes one arguments hash, computed from the tool name plus the canonical arguments. It expires. Changed arguments need a new approval. An old approval cannot be reused for a different payload.

The application runs the command only after that approval is valid and unexpired, and the command itself is idempotent. Replaying the same idempotency key with the same arguments returns the original result.

These actions stay refused: issuing a real payment, deleting a customer account, overriding refund policy, and changing an order total.

## Consequences

- A pending change is not a completed change.
- Operators can see what was approved and what executed.
- Tests can cover expiry, argument mismatch, and replay without a payment provider.
