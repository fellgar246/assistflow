# ADR 0016: Side effects run after the response

## Status

Accepted

## Context

A ticket, an escalation, a consumed approval, and a resolved conversation each need a follow-up: a notice, an audit row, a short summary, and sometimes a marker for later evaluation. Those steps can be slow. The customer request should not wait for them, and a failure in a follow-up should not undo the change the customer already saw.

## Decision

The command writes an outbox row in the same transaction as the business change. The row names the event, the tenant, a correlation id, an event id, and the entity ids that follow-up needs. It does not store a model payload or a secret. Replay of an idempotent command does not write a second row.

The HTTP handler commits, returns the response, and only then publishes the row. Publish failure is logged. The row stays pending for a later attempt. The business transaction is not rolled back.

The local publisher is an in-process queue. A background task drains it after the response. The hosted publisher is EventBridge when a bus name is set, otherwise SQS. That client is constructed only when `AWS_ENABLED` and `ASYNC_WORKERS_ENABLED` are both true and `LOCAL_ONLY_MODE` is false. `LOCAL_ONLY_MODE=true` forces the in-process queue. Terraform creates the queue, the bus, and the consumer only when `enable_async_workers` is true.

The in-process queue and the hosted consumer call the same handlers. Each handler records the event id once. A second delivery does not write a second notice, audit row, summary, or evaluation marker. The notice is an in-app record. Email is a log line. The summary runs only for a resolved conversation, and a summary failure leaves that conversation resolved. The evaluation marker uses `EVAL_SAMPLE_RATE` (default `0.05`) and is deterministic for an event id.

## Consequences

- Ticket create, escalation, approval consumption, and resolve return before the follow-up finishes.
- A failed consumer leaves the customer response successful and the message available to try again.
- Replaying one event id does not duplicate the follow-up.
- Local mode does not construct an SQS or EventBridge client.
