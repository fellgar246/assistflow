# Diagnose a failed tool call

Use the correlation id on the response. The same id is on the HTTP record, the agent trace, the tool execution, and the audit event.

## 1. Copy the id

Send the request with `X-Correlation-Id`, or read the id the API returns on that header. An error response carries it too.

```bash
curl -sD - http://localhost:8000/health -H 'X-Correlation-Id: corr-order-lookup'
```

The header in the response is the id to follow.

## 2. Read the hop log

Each hop is one JSON line with `"event": "trace_hop"`. Filter on the correlation id. A failed `get_order` includes these `hop` values:

| Hop | What it means |
|---|---|
| `http` | The request, its status, and the tool error code when a tool failed |
| `conversation` | The conversation the message belongs to |
| `agent` | The turn. `runtime_trace_id` is the hosted runtime id when that path ran |
| `model` | One model call. The line has latency, not the prompt or the completion |
| `retrieval` | A policy search, when the turn retrieved documents |
| `gateway` | The tool gateway check |
| `tool` | The tool name, error code, and latency |
| `command` | The business lookup |

The customer response does not include a stack trace. Log lines do not include tokens, email, or raw model documents when the process is in `aws-demo` or `showcase`.

## 3. Read the stored records

In the API database, the same correlation id is on:

- `agent_traces.correlation_id`, with `runtime_invocation_id` when a hosted runtime handled the turn
- `tool_executions.tool_name`, `error_code`, and `latency_ms`
- `audit_events` for `tool.failed` or `tool.denied`

`GET /metrics` returns the same counter names the operations dashboard uses: `conversation_count`, `agent_turn_count`, `agent_latency_ms`, `model_input_tokens`, `model_output_tokens`, `tool_call_count`, `tool_failure_count`, `approval_requested_count`, `approval_accepted_count`, `approval_rejected_count`, `human_escalation_rate`, `rag_retrieval_count`, and `grounded_answer_failure_count`.

Labels are the tool name, the status, and the tenant id. A customer id or a free-form error string is not a label.

## 4. CloudWatch

The log groups and the dashboard are created only when `enable_observability` is true. The default is false. Log retention is 14 days. The dashboard widgets use the metric names above in the `AssistFlow` namespace.

`METRICS_ENABLED=true` publishes those metrics only when `AWS_ENABLED=true` as well. Local execution keeps the in-memory counters behind `GET /metrics` and does not construct a CloudWatch client.
