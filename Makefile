.DEFAULT_GOAL := help
COMPOSE := docker compose
RUN_BACKEND := $(COMPOSE) run --rm backend

help: ## List commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

env: ## Create .env from .env.example (keeps an existing one)
	@test -f .env && echo ".env already exists" || (cp .env.example .env && echo "created .env")

up: ## Build and start the stack (db, redis, backend, worker, frontend)
	@# Remove the frontend container *with* its anonymous node_modules/.next volumes, so new packages are picked up.
	@# (--renew-anon-volumes would leave every old copy behind as a dangling volume.)
	$(COMPOSE) rm --force --stop --volumes frontend
	$(COMPOSE) up --build

down: ## Stop the stack (data volumes are kept)
	$(COMPOSE) down

logs: ## Follow logs of all services
	$(COMPOSE) logs -f

migrate: ## Apply Django migrations to the active database
	$(COMPOSE) exec backend python manage.py migrate

makemigrations: ## Create Django migrations
	$(COMPOSE) exec backend python manage.py makemigrations

superuser: ## Create a Django admin user
	$(COMPOSE) exec backend python manage.py createsuperuser

shell: ## Django shell
	$(COMPOSE) exec backend python manage.py shell

sync-supabase: ## Copy local Postgres rows that Supabase lacks (needs SUPABASE_DATABASE_URL)
	$(RUN_BACKEND) python manage.py sync_to_supabase

test: ## Run the test suite (always against the local docker Postgres, never Supabase)
	$(RUN_BACKEND) pytest

lint: ## Lint backend (ruff, OpenAPI schema) and frontend (eslint, tsc, bun test)
	$(COMPOSE) run --rm --no-deps backend sh -c "ruff check . && ruff format --check . && python manage.py spectacular --validate --fail-on-warn --file /dev/null"
	$(COMPOSE) run --rm --no-deps frontend sh -c "bun run lint && bunx next typegen && bunx tsc --noEmit && bun test"

check: lint test ## Lint + tests: run before finishing any change

.PHONY: help env up down logs migrate makemigrations superuser shell sync-supabase test lint check
