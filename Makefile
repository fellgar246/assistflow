.PHONY: lint typecheck test up down lint-api lint-web lint-terraform typecheck-api typecheck-web terraform-validate test-api test-web

UV ?= uv

lint: lint-api lint-web lint-terraform

typecheck: typecheck-api typecheck-web terraform-validate

test: test-api test-web

up:
	docker compose up -d

down:
	docker compose down

lint-api:
	$(UV) run --directory apps/api ruff check .
	$(UV) run --directory apps/api ruff format --check .

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
