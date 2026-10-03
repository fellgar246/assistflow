# ADR 0020: The dev environment deploys through OIDC

## Status

Accepted

## Context

An operator needs a repeatable way to plan and destroy the dev stack. A shared static access key in CI would outlive the person who created it. Billing alerts are useful, and they are not a substitute for leaving expensive resources off.

PostgreSQL already stores conversations and tool executions. A second store needs an explicit rule, or it will drift.

## Decision

The dev stack uses an S3 backend and a DynamoDB lock. The bucket and the lock table are created once by `make aws-bootstrap`. The filled backend file is not committed.

`make aws-plan`, `make aws-deploy`, `make aws-smoke`, `make aws-cost-check`, and `make aws-destroy` are the operator interface. Smoke and the cost check fail with a local message when AWS credentials are missing. Destroy deletes the dev environment only. Production is out of scope.

GitHub Actions on the main branch, and a manual dispatch, assume a deploy role with OIDC. The role trusts this repository's `dev` environment. Its policy lists deploy actions for this project and denies attaching `AdministratorAccess`. Pull requests do not deploy. The hosted agent remains a separate manual workflow.

The monthly budget is $5, with alerts at $1, $3, and $5. Alerts do not turn features off. Hosted agent, memory, managed retrieval, schedules, and Cognito stay off unless their flags are set.

PostgreSQL remains the system of record. DynamoDB metadata tables are optional and are not written by the application.

Bedrock invoke permission names the configured model and, when set, the configured guardrail. It does not allow every Bedrock action on every resource.

## Consequences

- A default plan creates none of the optional AI resources.
- CI can obtain AWS credentials only on the trusted deploy path, and only through OIDC.
- Two applies from an empty account converge on the same dev stack. Destroy leaves a follow-up plan with no resources from this stack.
- A missing credential does not look like a successful smoke or cost check.
