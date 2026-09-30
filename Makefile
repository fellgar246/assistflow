.PHONY: lint typecheck test up down seed lint-api lint-web lint-terraform typecheck-api typecheck-web terraform-validate test-api test-web deploy-agentcore smoke-agentcore

PYTHON_PATHS := src tests \
	../../services/conversations/src \
	../../services/customers/src \
	../../services/orders/src \
	../../services/shipping/src \
	../../services/returns/src \
	../../services/refunds/src \
	../../services/tickets/src \
	../../services/knowledge/src \
	../../packages/contracts/src \
	../../packages/test-fixtures/src \
	../../agent/runtime/src \
	../../agent/tools/src \
	../../agent/tools/tests \
	../../scripts

UV ?= uv

lint: lint-api lint-web lint-terraform

typecheck: typecheck-api typecheck-web terraform-validate

test: test-api test-web

up:
	docker compose up -d

down:
	docker compose down

lint-api:
	$(UV) run --directory apps/api ruff check $(PYTHON_PATHS)
	$(UV) run --directory apps/api ruff format --check $(PYTHON_PATHS)

seed:
	$(UV) run --directory apps/api python -m assistflow_api.seed

lint-web:
	npm --prefix apps/web run lint

lint-terraform:
	terraform fmt -check -recursive infra

typecheck-api:
	$(UV) run --directory apps/api mypy

typecheck-web:
	npm --prefix apps/web run typecheck

terraform-validate:
	terraform -chdir=infra/environments/dev init -backend=false -input=false
	terraform -chdir=infra/environments/dev validate

test-api:
	$(UV) run --directory apps/api pytest

test-web:
	npm --prefix apps/web test

# Operator commands. Pull-request checks do not run these targets.
deploy-agentcore:
	$(UV) run --directory apps/api python ../../scripts/deploy_agentcore.py --apply

smoke-agentcore:
	$(UV) run --directory apps/api python ../../scripts/smoke_agentcore.py
