# ADR 0010: The retrieval provider is configuration

## Status

Accepted

## Context

Policy answers already come from a tenant-scoped index. Moving the documents to object storage, or to a managed knowledge base, should not make the assistant loop import a cloud client or choose a provider.

## Decision

Callers depend on one retriever port. `RAG_PROVIDER=local` is the default and scores the in-process index. `RAG_PROVIDER=s3` scores the same product files after an operator syncs them into a private bucket whose keys include the tenant id. `RAG_PROVIDER=managed` is constructed only when managed retrieval is enabled, and it requires a metadata filter or a knowledge base per tenant. `LOCAL_ONLY_MODE=true` forces the local provider. Hits that cannot be cited are dropped. The document bucket and the knowledge base are Terraform modules that stay off unless an operator enables them. The bucket blocks public access. Both modules use the standard tags.

## Consequences

- Changing the provider does not change the assistant loop.
- Tests use an in-memory object store and a fake retrieve client. They do not call AWS.
- A missing tenant filter fails at startup.
- A default apply creates no knowledge base and no document bucket.
