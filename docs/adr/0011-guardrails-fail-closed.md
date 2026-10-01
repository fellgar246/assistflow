# ADR 0011: Guardrails are optional and fail closed

## Status

Accepted

## Context

The model can propose a tool, repeat a secret, or quote a document that tells it to take an action. Those strings are not authorization. A hosted content filter can add another check, but local tests have to pass without that service.

## Decision

The application allowlist, schema checks, tenant scope, document wrapper, and redaction run on every turn. Redaction removes bearer tokens, AWS access-key ids, and card numbers from replies, tool summaries, traces, and logs. A verbatim slice of the system prompt is replaced with one stable refusal.

`NoOpGuardrailFilter` is the default. `BedrockGuardrailFilter` is constructed only when `BEDROCK_ENABLED` and `GUARDRAILS_ENABLED` are both true and a guardrail id is set. Filter strengths come from configuration. An enabled filter with no id, or a client error, refuses the turn. Each filter call counts toward `MAX_MODEL_CALLS_PER_TURN`. A blocked input does not start the tool loop. When the reply was composed from tools, a grounding or redaction rewrite does not replace those facts.

`LOCAL_ONLY_MODE=true` forces the flag off. Tests use the no-op filter and a fake client. They do not call the live service.

## Consequences

- Unauthorized tool names are denied on the local gateway, the hosted gateway, and the turn loop.
- A pasted card or token is not stored in full.
- Turning the hosted filter on without a working client stops the turn.
- Order facts still come from tools.
