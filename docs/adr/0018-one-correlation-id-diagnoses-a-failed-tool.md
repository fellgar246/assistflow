# ADR 0018: One correlation id diagnoses a failed tool

## Status

Accepted

## Context

A failed lookup can pass through the HTTP request, the conversation, the agent turn, a model call, retrieval, the tool gateway, the tool, and the business command. Operators need one id that ties those records together. Metrics need stable names. Logs must not keep tokens or raw model documents. A dashboard is useful in a demonstration account and expensive to leave on by accident.

## Decision

The API accepts `X-Correlation-Id` or assigns one, and returns it on every response, including errors. The same id is stored on the agent trace, the tool execution, and the audit event, and each hop writes a `trace_hop` log line with the tool name, error code, and latency. The hosted runtime id, when the turn used one, stays on that same trace row.

structlog binds the correlation id, the tenant id, and the conversation id. It does not bind an email address or a raw token. In `aws-demo` and `showcase`, log lines drop raw model documents. Bearer tokens, access-key ids, and card numbers are redacted in every mode.

Counters use a metrics port. Tests and local execution read an in-memory recorder from `GET /metrics`. A CloudWatch publisher is constructed only when `AWS_ENABLED=true` and `METRICS_ENABLED=true`. Labels are limited to tool name, status, and tenant id.

Terraform creates the log groups and the dashboard only when `enable_observability` is true. The default is false. Retention is 14 days. The dashboard widgets use the same metric names the process emits.

## Consequences

- A failed tool call can be reconstructed from the response header without a stack trace in the customer reply.
- Local development does not create CloudWatch resources and does not import the AWS SDK for metrics.
- Turning the dashboard on is an explicit apply. Revalidate CloudWatch prices before that apply.
