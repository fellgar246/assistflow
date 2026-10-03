.PHONY: lint typecheck test eval up down seed lint-api lint-web lint-terraform typecheck-api typecheck-web terraform-validate test-api test-web deploy-agentcore smoke-agentcore smoke-gateway sync-knowledge aws-bootstrap aws-plan aws-deploy aws-smoke aws-cost-check aws-destroy

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
	../../agent/memory/src \
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

# Local golden scenarios. This target does not call a hosted model or hosted evaluations.
eval:
	$(UV) run --directory apps/api python -m assistflow_api.evaluate

# Operator commands. Pull-request checks do not run these targets.
deploy-agentcore:
	$(UV) run --directory apps/api python ../../scripts/deploy_agentcore.py --apply

smoke-agentcore:
	$(UV) run --directory apps/api python ../../scripts/smoke_agentcore.py

smoke-gateway:
	$(UV) run --directory apps/api python ../../scripts/smoke_gateway.py

sync-knowledge:
	$(UV) run --directory apps/api python -m assistflow_api.sync_knowledge

# Dev environment. Pull-request checks do not run these targets.
aws-bootstrap:
	$(UV) run --directory apps/api python ../../scripts/dev_environment.py bootstrap

aws-plan:
	$(UV) run --directory apps/api python ../../scripts/dev_environment.py plan

aws-deploy:
	$(UV) run --directory apps/api python ../../scripts/dev_environment.py deploy

aws-smoke:
	$(UV) run --directory apps/api python ../../scripts/dev_environment.py smoke

aws-cost-check:
	$(UV) run --directory apps/api python ../../scripts/dev_environment.py cost-check

aws-destroy:
	$(UV) run --directory apps/api python ../../scripts/dev_environment.py destroy
