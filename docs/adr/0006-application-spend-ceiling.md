# ADR 0006: AWS spend has an application ceiling

## Status

Accepted

## Context

Billing alerts arrive after usage exists. A pull request or a default boot must not create a hosted agent, a hosted model call, managed retrieval, or a schedule. Engineering targets are still useful so a demo has a ceiling before anyone applies infrastructure.

## Decision

Feature flags are the hard stop. Billing alerts do not replace them.

Safe infrastructure defaults:

- hosted agent off;
- long-term memory off;
- managed retrieval off;
- schedules off.

`LOCAL_ONLY_MODE=true` disables the assistant and discretionary AWS features. The local app still serves health, domain reads, and stored conversations. A chat turn stores an acknowledgement and does not call a model. `AI_ENABLED=false` stops the assistant even when AWS flags stay on.

Session, tool, token, and memory caps live in one module. The runner, the gateway, and memory ask that module before provider work. A full daily session quota is a typed API error. The hosted gateway control plane cannot express a per-session tool throttle, so the application cap applies in local mode and on the hosted tool function.

Support agents read session, token, and tool counters from the process. The cost view may link to the budgets console. It does not call a billing API. aws-demo keeps successful traces short and still logs failures with the correlation id.

CloudWatch log groups created by this stack keep logs for 14 days or less. A cleanup command lists resources tagged `Project=assistflow` and `AutoCleanup=true`. It deletes nothing unless the operator executes it, and it refuses every environment except dev. The cost check, when credentials exist, also reads the deployed API task and expects the kill switches to stay off.

When AWS resources are applied later, they carry these tags: `Project=assistflow`, `Environment=dev`, `ManagedBy=terraform`, `CostCenter=learning`, `AutoCleanup=true`.

Engineering budget targets, which are targets and not a cloud invoice guarantee:

- local development: about $0 AWS;
- light AWS demo: at most $5 in a month;
- temporary showcase mode: at most $10 in a month.

Revalidate current prices before any deployment. Do not hard-code a vendor price into domain logic. Static AWS access keys are never committed. Deploy automation, when it exists, assumes a role through short-lived credentials.

The foundation stack validates Terraform and does not apply it.

## Consequences

- Default boot performs no billable cloud call.
- Optional hosted features stay disabled until an operator turns them on.
- A budget module exists for a later apply. Creating that budget is itself off by default.
