# ADR 0007: Local knowledge index

## Status

Accepted

## Context

Policy answers need a source the application can check. A hosted embedding API would make the default profile depend on a network and a billable model.

## Decision

Published help articles are chunked, checksummed, and stored per tenant. A deterministic embedder fills the local index. Retrieval scores those vectors in process and returns only the latest published version for that tenant. Article text sent to the model is wrapped as untrusted data. If no chunk meets the score floor, the assistant abstains and the trace records a grounded-answer failure.

## Consequences

- Ingest and query run with the local retrieval provider and with AWS disabled.
- Tests never call a hosted embedding API.
- A changed document checksum stores a new version. An unchanged checksum does nothing.
