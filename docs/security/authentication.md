# Authentication

Customers and support agents present an RS256 access token. The API verifies the signature and reads the tenant and the role from the claims. A value in the request body does not choose the tenant.

## Claims

| Claim | Accepted names | Meaning |
|---|---|---|
| Tenant | `tenant_id`, `custom:tenant_id` | Tenant the caller may access |
| Role | `role`, `custom:role`, or a `cognito:groups` entry of `customer` or `support_agent` | Customer or support agent |
| Customer | `customer_id`, `custom:customer_id` | Required when the role is `customer` |
| Agent | `agent_id`, `custom:agent_id` | Required when the role is `support_agent` |

The audience must match `AUTH_AUDIENCE`. A customer token on a staff route is forbidden. A missing or invalid token on a protected route is unauthorized. The failure is logged as `authorization_denied` with the reason, the method, and the path. The raw token is not written.

## Browser session

The web app does not store the access token in `localStorage`. Local sign-in calls `POST /dev/issuer/session`. The API sets an HttpOnly cookie named `assistflow_session` (SameSite=Lax, path `/`, eight hours). On local HTTP the cookie is not marked Secure. The response body is the person's name, organization, and role. It does not contain the token. The web app sends the cookie with `credentials: "include"` through the `/api` rewrite, so the cookie stays on the web origin.

`POST /dev/issuer/token` returns a bearer token for tests. The login page does not call it.

Logs drop `authorization`, `cookie`, `access_token`, `refresh_token`, `assistflow_session`, and `token` before other redaction.

## Local issuer and remote pools

`EXECUTION_MODE=local` uses a process-generated RSA key. The issuer is `https://assistflow.local` and the audience is `assistflow-api`. Keys are not production secrets.

`aws-demo` and `showcase` refuse to start when `AUTH_ISSUER` is empty or equals the local issuer, or when `AUTH_AUDIENCE` is empty. The remote verifier rejects a token whose issuer is the local issuer before it requests a JWKS document. `AUTH_JWKS_URL` defaults to `{AUTH_ISSUER}/.well-known/jwks.json`. Tests use the local verifier and do not call a live pool.

Terraform creates the user pool only when `enable_cognito` is true. The default is false.
