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

The home page does not call a model. The API does not load a cloud SDK while AWS is disabled.

Stop the database with `make down`.

`LOCAL_ONLY_MODE=true` forces hosted-agent, hosted-model, managed-retrieval, and long-term-memory flags off, even if other variables request them. Credentials are read from the environment only. Do not commit a filled `.env` file.

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
