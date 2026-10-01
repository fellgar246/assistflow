# ADR 0012: Low-risk writes are idempotent and sensitive writes wait

## Status

Accepted

## Context

Support can open a ticket, add a note, or ask a person to join. Those writes are low risk, and clients retry them. A second try must not open a second ticket, note, or escalation.

Address changes, returns, and refund requests are sensitive. The assistant can check whether an order is eligible. It must not apply the change because a model proposed it.

## Decision

Each low-risk write takes an idempotency key. The stored record is the tenant, the key, the tool name, a hash of the arguments, and a short result. The unique constraint is the tenant plus the key. The same key and the same arguments return the stored result and do not run the write again. The same key with different arguments is a conflict, and the original row stays as it was. The write, its audit event, and the idempotency record commit in one transaction. A timeout does not retry the write. The client retries by sending the same key.

Eligibility checks are reads. They return the fixture decision and do not change a row.

Sensitive writes are implemented behind an application approval grant. The agent loop and the tool gateway cannot mint that grant, and the model cannot pass it as an argument. Without the grant, an eligible proposal waits and an ineligible order is denied with a reason code. The order, return, and refund rows stay unchanged. With the grant, the command runs once for the key. A refund request stays a request: it is never marked paid, and it never stores a payment instrument.

When the tool gateway adapter is enabled, it may list and run the low-risk writes. It may list the sensitive writes as requiring approval. Their mutate path stays in the application.

Successful writes and denied writes each append an audit event. A replay does not append another business event.

## Consequences

- Repeating a ticket, note, or escalation cannot duplicate it.
- A person still has to approve an address change, a return, or a refund request before it is saved.
- Tests can replay a key, conflict a key, and show that the agent path does not mutate sensitive rows.
