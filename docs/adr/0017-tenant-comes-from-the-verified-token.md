# ADR 0017: The tenant comes from the verified token

## Status

Accepted

## Context

Customers and support agents need a real identity. A tenant id sent in a header or a body can be forged, and a customer of one tenant must not read another tenant's orders, tickets, conversations, documents, or preferences. Tests need a deterministic issuer. A demonstration pool must stay off until an operator turns it on, and continuous integration must not call a live pool.

## Decision

Access tokens are RS256. They carry `tenant_id` and `role` (`customer` or `support_agent`). A customer token also carries `customer_id`. A support token carries `agent_id`. The API verifies the signature and builds the caller from those claims. Routes ignore `tenant_id` and `customer_id` in the body.

Local mode issues tokens from a process-generated RSA key. The issuer is `https://assistflow.local` and the audience is `assistflow-api`. The browser stores that token in an HttpOnly cookie named `assistflow_session` (SameSite=Lax, path `/`, not Secure on local HTTP, eight hours). The login response does not include the token, and logs drop authorization, cookie, and token fields. `aws-demo` and `showcase` refuse to start when the configured issuer is empty or is the local issuer. A remote verifier rejects a local-issuer token before it fetches a JWKS document.

A customer token cannot call a staff route. A support token cannot call a customer route. Lists and reads for orders, shipments, tickets, conversations, and preferences are limited to the token's tenant and, where the resource is customer-scoped, to that customer. Published documents are limited to the token's tenant. Tool calls use the same verified caller. The hosted gateway receives that caller in the signed `x-actor-context` header. A `tenant_id` argument on a tool is refused.

Terraform creates a user pool, an app client, and the `customer` and `support_agent` groups only when `enable_cognito` is true. The default is false, so a normal plan creates no pool.

## Consequences

- Cross-tenant reads and writes fail closed without returning the other tenant's payload.
- Local tests mint tokens from the app under test. They do not contact a user pool.
- The web app does not keep the access token in `localStorage`.
- Staff inbox routes stay available outside local mode, and they require a verified support-agent token.
