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

`LOCAL_ONLY_MODE=true` disables discretionary AI and AWS features. The local app keeps working.

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
