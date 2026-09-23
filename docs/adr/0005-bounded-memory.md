# ADR 0005: Memory is bounded

## Status

Accepted

## Context

An agent that remembers everything will store secrets, payment details, and unrestricted support history. Unbounded session memory also makes a turn more expensive and harder to delete.

## Decision

Memory is an application limit, not a prompt suggestion.

- Session memory is capped, including the number of memory events stored for one session.
- Long-term memory is off by default.
- When long-term memory is enabled, it may store only scoped low-risk preferences such as preferred language and preferred contact channel.
- Each long-term memory type needs a purpose, a retention period, deletion semantics, an owner, and a retrieval policy.
- Payment data, credentials, and unrestricted support history are not memory.

Exceeding a memory or turn limit stops the turn with a safe error. The application does not retry without a bound.

## Consequences

- The local profile boots with long-term memory disabled.
- Deletion and retention are part of the memory design before any store is written.
- Logs and memory follow the same rule: keep a safe summary instead of a secret or a raw tool payload.
