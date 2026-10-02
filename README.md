# AssistFlow

Local-first customer support application. The default profile runs the web app, the API, and PostgreSQL on your machine. Hosted agent, hosted model, managed retrieval, and long-term memory stay off, so a normal boot does not call AWS.

## Prerequisites

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- Node.js 20 or newer
- Docker
- Terraform 1.6 or newer, for the infrastructure checks

## Profile A (local)

From the repository root:

```bash
cp .env.example .env
uv sync --all-packages --all-groups
npm --prefix apps/web install
make up
```

`make up` starts PostgreSQL with the pgvector image on port 54329, so it does not take over another Postgres already listening on 5432. The default database URL is:

```text
postgresql+psycopg://assistflow:assistflow@localhost:54329/assistflow
```

Start the API and the web app in two terminals:

```bash
uv run --directory apps/api uvicorn assistflow_api.main:app --reload --host 127.0.0.1 --port 8000
npm --prefix apps/web run dev
```

- API health: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- Web home: [http://127.0.0.1:3000](http://127.0.0.1:3000)
- Customer chat: [http://127.0.0.1:3000/chat](http://127.0.0.1:3000/chat)
- Support inbox: [http://127.0.0.1:3000/agent/inbox](http://127.0.0.1:3000/agent/inbox)

The home page does not call a model. The API does not load a cloud SDK while AWS is disabled.

Apply the database schema and load the demo support data:

```bash
uv run --directory apps/api alembic upgrade head
make seed
```

`make seed` can be run again. It updates the same customers, orders, shipments, and tickets instead of inserting duplicates. The fixture file is `knowledge/fixtures/support_domain.json`. It also ingests the published help articles under `knowledge/policies` and `knowledge/product-docs` for each demo tenant. Re-running ingest leaves an unchanged checksum in place. `python -m assistflow_api.ingest_knowledge` from `apps/api` reloads those articles without reseeding orders.

Demo tenant `11111111-1111-4111-8111-111111111111` (Harbor Goods) includes order `ORD-10482`, an in-transit shipment from the DFW hub, and one open ticket. Demo tenant `22222222-2222-4222-8222-222222222222` (Fieldline Supply) has a different order, `ORD-20817`. Send the tenant on every support request:

```text
X-Tenant-Id: 11111111-1111-4111-8111-111111111111
```

Conversation routes also need the customer. Both values come from these headers. The API does not take a tenant id from the request body.

```text
X-Customer-Id: aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaa0001
```

`X-Correlation-Id` is optional. When it is omitted, the API assigns one and returns it on the response. Audit events for that request store the same id.

Low-risk writes run once for each idempotency key: a ticket, a ticket note, or an escalation. Sending the same key and the same arguments again returns the original result. A sensitive change — shipping address, return, or refund request — is checked for eligibility first. An eligible proposal is saved as a pending approval for 15 minutes and shown in the chat as a diff. Nothing is written until the customer confirms that approval. Confirm and cancel send only the approval id. The server reloads the stored arguments, checks that the approval is still pending and unexpired, and checks the arguments hash again. The business write and the consumed approval commit together. Confirming twice returns the same result and does not write again. Cancelling or letting the approval expire leaves the order unchanged. The model cannot pass an approval flag. A refund request is never marked paid and never stores a payment instrument.

Support reads:

| Method | Path |
|---|---|
| GET | `/customers` and `/customers/{customer_id}` |
| GET | `/orders` and `/orders/{order_number}` |
| GET | `/orders/{order_number}/shipment` |
| GET | `/orders/{order_number}/eligibility/address-change` |
| GET | `/orders/{order_number}/eligibility/return` |
| GET | `/orders/{order_number}/eligibility/refund` |
| GET | `/tickets` and `/tickets/{ticket_id}` |
| POST | `/tickets` |
| POST | `/conversations` |
| GET | `/conversations` |
| POST | `/conversations/{conversation_id}/messages` |
| GET | `/conversations/{conversation_id}/messages` |
| POST | `/conversations/{conversation_id}/approvals/{approval_id}/confirm` |
| POST | `/conversations/{conversation_id}/approvals/{approval_id}/reject` |
| GET | `/preferences` |
| DELETE | `/preferences` |
| GET | `/dev/staff` |
| GET | `/staff/inbox` |
| GET | `/staff/conversations/{conversation_id}` |
| GET | `/staff/conversations/{conversation_id}/messages` |
| GET | `/staff/conversations/{conversation_id}/trace` |
| POST | `/staff/conversations/{conversation_id}/takeover` |
| POST | `/staff/conversations/{conversation_id}/messages` |
| POST | `/staff/conversations/{conversation_id}/resolve` |
| POST | `/staff/conversations/{conversation_id}/approvals/{approval_id}/confirm` |
| POST | `/staff/conversations/{conversation_id}/approvals/{approval_id}/reject` |
| GET | `/staff/tickets/{ticket_id}` |

`POST /conversations/{conversation_id}/messages` stores the customer text. When `AI_ENABLED=true` (the local default), the API runs an in-process assistant and stores its reply plus a trace. That reply asks for an order number or a narrower question. It does not state a delivery date, and it does not call a hosted model. When `AI_ENABLED=false`, the route stores one fixed acknowledgement on the first customer message and does not state an order fact. History sent to the assistant is the newest 20 messages, and older messages are also dropped while a four-characters-per-token estimate exceeds 4000. Older rows stay in the database. `GET /conversations/{conversation_id}` returns one conversation for the current customer. `POST /tickets` may include `conversation_id` when the conversation is open in the same tenant.

A resolved conversation stays closed. When the customer sends another message, the API opens a new conversation, stores the message there, and returns that id in `X-Conversation-Id`. The previous thread is unchanged.

While `EXECUTION_MODE=local`, `GET /dev/actors` lists the seeded customers the chat can act as. The chat shows that choice in a control marked "Development only". It is a named customer, not a tenant id field, and the route is not available in other execution modes. `GET /dev/staff` lists the seeded support agents the same way. Staff routes read `X-Tenant-Id` and `X-Agent-Id`. They are development-only and return not found outside local mode. The inbox lists conversations that are escalated or waiting for confirmation, newest update first. Take over assigns the conversation and its ticket. A human reply is stored as an assistant message with author type `support_agent`, so the customer thread can label it as a person. Resolve closes the conversation and the linked ticket, and repeating it does not close them again. Staff confirmation of a pending change uses the same stored arguments and hash check as the customer confirmation, and records the staff agent as `approved_by`. The trace summary shows kind, tool name, status, latency, and an error code. It does not include provider payloads. The web app proxies `/api/*` to the API. The console does not call a model to render a page.

List routes take `limit` (default 20, maximum 100) and an opaque `cursor`. The generated API document is at [http://127.0.0.1:8000/openapi.json](http://127.0.0.1:8000/openapi.json).

Stop the database with `make down`.

`LOCAL_ONLY_MODE=true` forces hosted-agent, hosted-model, guardrail, managed-retrieval, and long-term-memory flags off, and it forces retrieval back to the local index even if `RAG_PROVIDER` names an AWS provider. Credentials are read from the environment only. Do not commit a filled `.env` file.

## Retrieval

Policy answers use one retriever port. The default provider is the local index. `RAG_PROVIDER=s3` scores the same product files after `make sync-knowledge` uploads them to `KNOWLEDGE_BUCKET`. Keys always include the tenant id. `RAG_PROVIDER=managed` calls a knowledge base only when `MANAGED_RAG_ENABLED=true`, and startup fails unless a metadata filter or a base per tenant is set. The assistant loop does not choose the provider. A normal Terraform apply leaves the document bucket and the knowledge base uncreated. Revalidate current retrieval prices before you apply either module. This repository does not embed a provider price.

## Hosted agent runtime

The default API runs the assistant in-process. A hosted runtime uses the same turn contract and stays off until you enable it.

Revalidate current AgentCore runtime pricing before you apply anything. This repository does not embed a provider price.

Pull-request checks do not package or deploy the runtime. Apply it yourself:

```bash
export AGENTCORE_ENABLED=true
export AGENTCORE_CONTAINER_IMAGE_URI=<your-image-uri>
make deploy-agentcore
```

`make deploy-agentcore` packages the agent sources and applies the dev stack with `enable_agentcore=true`. Without `AGENTCORE_ENABLED=true` and an image URI, the command stops before Terraform runs. The dev stack's `enable_agentcore` variable defaults to false, so a normal apply creates no runtime resource.

Smoke compares seeded order facts (status, hub, estimated delivery date, and the tools used). It skips when `AGENTCORE_RUNTIME_ARN` or cloud credentials are missing:

```bash
make smoke-agentcore
```

## Hosted tool gateway

Business reads from the hosted agent go through a tool gateway. The local profile uses an in-process gateway and does not call that endpoint.

The gateway is created only when `enable_agentcore` is true. A normal apply leaves it off. Revalidate current AgentCore gateway pricing before you apply. This repository does not embed a provider price.

`make deploy-agentcore` packages the read-tool function and applies it with the runtime. Set these only in the environment, not in a committed file:

```text
GATEWAY_INBOUND_TOKEN
AGENTCORE_ACTOR_CONTEXT_SECRET
DATABASE_URL
```

The runtime authenticates to the gateway with IAM. The gateway calls the tool function with its own role, limited to that function. The tenant id is a signed context from the server session. The model cannot supply it as a tool argument.

Smoke calls `tools/list` and `tools/call` for the seeded order. It skips when `AGENTCORE_GATEWAY_URL`, the actor-context secret, or credentials are missing:

```bash
make smoke-gateway
```

Pull-request checks do not run either smoke command.

## Guardrails

Tool allowlisting, argument checks, tenant scope, and redaction run in every environment. Bearer tokens, AWS access-key ids, and card numbers are removed from stored replies, tool summaries, traces, and logs.

`GUARDRAILS_ENABLED=true` adds a hosted filter only when `BEDROCK_ENABLED=true`. The filter checks the customer message before any tool runs and checks the reply before it is stored. A filter error refuses the turn. Set `GUARDRAIL_ID` to the resource that uses the strengths in the environment. An empty id refuses the turn and does not construct a client. Local tests use the no-op filter. Order facts still come from tools when a grounding check is enabled.

## Memory

`SHORT_TERM_MEMORY_ENABLED` defaults to false. When it is on, the conversation keeps the last order id and the last shipment status until `MAX_SESSION_MINUTES`, and it stops after `MAX_MEMORY_EVENTS_PER_SESSION` events. Those facts are not the transcript, and they do not skip the tenant check on a tool.

`LONG_TERM_MEMORY_ENABLED` defaults to false. When it is on, the only stored preferences are preferred language (`en`, `es`) and preferred contact channel (`web`, `email`). Each row has a purpose, an owner, and a retention deadline. `GET /preferences` lists them for the current customer. `DELETE /preferences` removes them. A card number, a password, or any other key is rejected.

A hosted memory client is built only when `AGENTCORE_ENABLED=true` and the matching flag is on. Set `AGENTCORE_MEMORY_ID` for that client. With the hosted runtime off, the same flags use local tables. With both flags off, no memory client is constructed, and an address change still waits for approval.

A fixed set of 10 address follow-ups is compared in [the session-memory note](docs/evaluations/session-memory-follow-ups.md).

## Quality gates

```bash
make lint
make typecheck
make test
```

| Target | What it runs |
|---|---|
| `lint` | Ruff, ESLint, and `terraform fmt -check` |
| `typecheck` | mypy, TypeScript, and `terraform validate` |
| `test` | pytest and Vitest |
| `up` / `down` | PostgreSQL via Docker Compose |
| `deploy-agentcore` | Operator-only hosted runtime package and apply |
| `smoke-agentcore` | Operator-only hosted order-fact check; skips without credentials |
| `smoke-gateway` | Operator-only hosted tools/list and tools/call; skips without credentials |

Browser tests are scaffolded with Playwright and are not part of `make test`. Install browsers first, then run `npm --prefix apps/web run test:e2e`.

## Layout

| Path | Role |
|---|---|
| `apps/web` | Next.js customer and operator UI |
| `apps/api` | FastAPI application |
| `packages/contracts` | Shared schemas, no I/O |
| `packages/test-fixtures` | Shared fixture builders |
| `agent/` | Agent runtime, prompts, tools, and memory |
| `services/` | Commerce and support services |
| `infra/` | Terraform modules and the dev environment |
| `docs/architecture` | How a request is authorized |
| `docs/adr` | Architecture decisions |

## Decisions

Read [the architecture overview](docs/architecture/overview.md) and the records in [docs/adr](docs/adr/README.md). The agent proposes actions. The application authorizes them. Local execution is the default, and spend is capped by feature flags rather than by a prompt.
