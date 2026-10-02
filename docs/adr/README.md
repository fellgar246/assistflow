# Architecture decision records

| Record | Decision |
|---|---|
| [0001](0001-agent-proposes-application-authorizes.md) | The agent proposes and the application authorizes |
| [0002](0002-local-first-execution.md) | Local execution is the default |
| [0003](0003-tools-cross-a-gateway-boundary.md) | Tool calls cross a gateway boundary |
| [0004](0004-sensitive-writes-need-human-approval.md) | Sensitive writes need human approval |
| [0005](0005-bounded-memory.md) | Memory is bounded |
| [0006](0006-application-spend-ceiling.md) | AWS spend has an application ceiling |
| [0007](0007-local-knowledge-index.md) | Policy answers come from a local tenant index |
| [0008](0008-hosted-runtime-is-opt-in.md) | The hosted runtime is opt-in |
| [0009](0009-business-reads-use-the-tool-gateway.md) | Business reads use the tool gateway |
| [0010](0010-retrieval-provider-is-configuration.md) | The retrieval provider is configuration |
| [0011](0011-guardrails-fail-closed.md) | Guardrails are optional and fail closed |
| [0012](0012-idempotent-writes-and-approval-gate.md) | Low-risk writes are idempotent and sensitive writes wait |
| [0013](0013-customer-approvals-expire.md) | Customer approvals expire and bind one arguments hash |
| [0014](0014-session-memory-is-separate-from-the-transcript.md) | Session memory is separate from the transcript |
| [0015](0015-human-and-assistant-share-a-conversation.md) | A person and the assistant share one conversation |
| [0016](0016-side-effects-run-after-the-response.md) | Side effects run after the response |
| [0017](0017-tenant-comes-from-the-verified-token.md) | The tenant comes from the verified token |
| [0018](0018-one-correlation-id-diagnoses-a-failed-tool.md) | One correlation id diagnoses a failed tool |
| [0019](0019-local-evaluation-suite-is-the-gate.md) | The local evaluation suite is the gate |
