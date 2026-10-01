# ADR 0013: Customer approvals expire and bind one arguments hash

## Status

Accepted

## Context

A shipping address, a return, and a refund request are sensitive. The assistant can tell whether an order is eligible. It must not apply the change because a model proposed it, and it must not treat a boolean in the tool arguments as permission.

The customer needs to see the difference and decide. A confirmation has to stay tied to the exact proposal, and it cannot be reused after it expires or after the arguments change.

## Decision

An eligible tier 2 proposal writes an approval and a tool execution in one transaction. The approval id is a random UUID. It stores the canonical arguments, a hash of the tool name plus those arguments, a diff that is safe to render, and an expiry 15 minutes after the request. The conversation waits for confirmation. The assistant message names the pending action and does not claim it already happened.

Confirm and cancel are HTTP routes on the conversation. The body cannot carry a replacement payload. Confirm loads the stored arguments, refuses the call when the approval is expired, rejected, or the hash no longer matches, and otherwise runs the idempotent domain command. The command and the consumed approval commit together. A second confirm returns that outcome and does not write again. Cancel and expiry leave the business rows unchanged. A read that finds a pending approval past its expiry marks it expired.

Audit events record requested, approved, rejected, expired, and consumed. Return and refund proposals use the same approval and the same card, with a diff of the reason and, for a refund, the amount. A refund request is never marked paid and never stores a payment instrument.

## Consequences

- The customer confirms or cancels in the chat before a sensitive row changes.
- A stale or edited approval cannot be applied to a different payload.
- The model still cannot approve its own proposal.
