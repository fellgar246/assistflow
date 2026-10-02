# ADR 0019: The local evaluation suite is the gate

## Status

Accepted

## Context

Prompt and tool changes need a report that can be compared from one run to the next. A hosted evaluation product can score the same scenarios later, but a pull request cannot depend on that service or on a model bill. Safety misses, such as a forbidden tool call, have to fail the check on a laptop with the network disabled.

## Decision

Golden scenarios live in `agent/evaluations/scenarios.json`. Each one has a stable id, a category, a tenant, a customer utterance, optional fixture overrides, and expectations. `make eval` runs them through the in-process assistant with the mock model and the local tool gateway. It writes a JSON report and a short Markdown summary under `test-results/evaluations/`.

The report always includes the same metric names, the prompt id, and the prompt version. Scenario ids do not change unless someone edits the file on purpose. Latency and token counts are recorded per scenario. Cost is estimated from those counts and `agent/evaluations/prices.json`. A model id that is not in that file stores a null cost.

Deterministic safety metrics fail the process: a forbidden tool was called, a cross-tenant read succeeded, an approval was skipped or applied early, or the step cap was exceeded. Qualitative scores are recorded as not run unless a judge is explicitly enabled. That judge is not the exit condition.

`HOSTED_EVALUATIONS` defaults to false. While it is false the suite does not construct a hosted evaluation client. Turning it on submits the same scenario ids through an injected client. The pull-request workflow runs `make eval` and does not call a hosted model or hosted evaluations.

Resolved conversations can still be marked for later review by the sample rate. Those markers can be listed. They are not part of the golden file.

## Consequences

- A prompt or tool change produces a diffable local report without an AWS account.
- A tier 3 tool call fails the pull request even when every other score passes.
- Hosted evaluations stay an operator choice. The price table stays empty until someone fills in current rates.
