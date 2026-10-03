# ADR 0002: Local-first execution

## Status

Accepted

## Context

Contributors need to run the product on a clean machine. Requiring an AWS account, a hosted model, or a hosted agent runtime would make the default path billable and would block work when those services are unavailable.

## Decision

The default profile is local. Missing configuration resolves to that profile:

- execution mode is local;
- AWS, the hosted agent, and the hosted model are off;
- retrieval uses the local database;
- long-term memory and managed retrieval are off.

Cloud adapters sit behind interfaces. Domain services must not import a hosted-model or hosted-agent client at import time while AWS is disabled. `LOCAL_ONLY_MODE=true` forces the assistant and those hosted flags off. The API still serves health checks, domain reads, and stored conversations, and it does not construct a hosted client.

A mock agent is allowed in local mode. That mock does not call a hosted model.

## Consequences

- `make up`, the API, and the web app are enough to boot the stack.
- Tests can exercise authorization and limits without cloud credentials.
- Hosted profiles are explicit opt-ins. They are not the default and they are not created by a pull request.
