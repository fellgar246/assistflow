# ADR 0014: Session memory is separate from the transcript

## Status

Accepted

## Context

A follow-up such as "change it to this address" can refer to an order that was already looked up. Copying the whole transcript into a memory store would keep secrets and payment details, and it would make deletion harder. The history window already carries recent text. A second store is only useful for a few structured facts, and only when an operator turns it on.

## Decision

Bounded conversation history stays on every turn. It is not a memory client.

Session memory is off unless `SHORT_TERM_MEMORY_ENABLED=true`. It stores the last order id and the last shipment status for that conversation, with a lifetime no longer than `MAX_SESSION_MINUTES` and at most `MAX_MEMORY_EVENTS_PER_SESSION` events. The facts are passed beside the transcript. A remembered order id is still checked against the tenant on the tool. Exceeding the event cap stops the turn. Values are redacted before they are written.

Long-term memory is off unless `LONG_TERM_MEMORY_ENABLED=true`. The only keys are `preferred_language` and `preferred_contact_channel`. Each row stores the value, a purpose, the tenant and customer who own it, and a retention deadline 365 days out. Other keys, payment numbers, and secrets are rejected and nothing is stored. The customer can delete their rows. Another tenant cannot read or delete them.

The hosted memory client is constructed only when `AGENTCORE_ENABLED=true` and the matching flag is on. Otherwise the local tables are used, or no client is built. Order, ticket, and approval behavior does not change when both flags are off.

## Consequences

- A normal local boot does not construct a memory client.
- Follow-ups can use the history window without session memory.
- When the window no longer holds the order, session memory supplies the last order id, and an empty window makes the assistant ask.
- Preferences stay limited to language and contact channel, with a purpose, an owner, and a deadline.
