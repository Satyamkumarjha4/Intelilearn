.DEFAULT_GOAL := help
COMPOSE := docker compose
RUN_BACKEND := $(COMPOSE) run --rm backend
# Backend and the repo-root tests/ (mounted at /tests); --config keeps the backend's ruff settings and first-party
# packages for both, since tests/ has no config of its own.
RUFF_PATHS := --config pyproject.toml . ../tests

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
	$(COMPOSE) run --rm --no-deps backend sh -c "ruff check $(RUFF_PATHS) && ruff format --check $(RUFF_PATHS) && python manage.py spectacular --validate --fail-on-warn --file /dev/null"
	$(COMPOSE) run --rm --no-deps frontend sh -c "bun run lint && bunx next typegen && bunx tsc --noEmit && bun test"

check: lint test ## Lint + tests: run before finishing any change

# --- Browser tests against the fake LLM (docs/testing.md) ---------------------------------------------------------
# Its own compose project, ports and database: no Supabase, no provider key, nothing shared with `make up`.
E2E_FRONTEND_PORT ?= 7100
E2E_BACKEND_PORT ?= 7110
E2E_STAFF_EMAIL ?= staff@example.com
E2E_STAFF_PASSWORD ?= E2e-staff-pass-1
E2E_COMPOSE := FRONTEND_PORT=$(E2E_FRONTEND_PORT) BACKEND_PORT=$(E2E_BACKEND_PORT) E2E_FRONTEND_PORT=$(E2E_FRONTEND_PORT) E2E_BACKEND_PORT=$(E2E_BACKEND_PORT) docker compose -p socra-e2e -f docker-compose.yml -f docker-compose.e2e.yml --profile e2e

fake-llm: ## Start the throwaway stack on a fake LLM (own database), with its registry and a staff user
	$(E2E_COMPOSE) up -d --build
	@echo "waiting for the API..."; for i in $$(seq 1 90); do curl -sf -o /dev/null http://localhost:$(E2E_BACKEND_PORT)/api/health && break; sleep 2; done; curl -sf -o /dev/null http://localhost:$(E2E_BACKEND_PORT)/api/health
	$(E2E_COMPOSE) exec -T backend python manage.py seed_registry --file /tests/e2e/fake_registry.json
	$(E2E_COMPOSE) exec -T -e STAFF_EMAIL=$(E2E_STAFF_EMAIL) -e STAFF_PASSWORD=$(E2E_STAFF_PASSWORD) backend python manage.py shell -c "import os; from accounts.models import User; u, _ = User.objects.get_or_create(email=os.environ['STAFF_EMAIL'], defaults={'name': 'Staff'}); u.is_staff = True; u.set_password(os.environ['STAFF_PASSWORD']); u.save()"
	@echo "up: http://localhost:$(E2E_FRONTEND_PORT)  (staff: $(E2E_STAFF_EMAIL))"

e2e: fake-llm ## Run the Playwright smoke tests against the fake-LLM stack (first run: cd e2e && bun install && bunx playwright install chromium)
	cd e2e && E2E_BASE_URL=http://localhost:$(E2E_FRONTEND_PORT) E2E_API_URL=http://localhost:$(E2E_BACKEND_PORT) E2E_STAFF_EMAIL=$(E2E_STAFF_EMAIL) E2E_STAFF_PASSWORD=$(E2E_STAFF_PASSWORD) bun run test

e2e-down: ## Stop the throwaway stack and delete its database
	$(E2E_COMPOSE) down -v

backend-log:
	$(COMPOSE) logs -f backend

frontend-log:
	$(COMPOSE) logs -f frontend

worker-log:
	$(COMPOSE) logs -f worker

db-log:
	$(COMPOSE) logs -f db

redis-log:
	$(COMPOSE) logs -f redis

reload: #rebuilds backend and frontend
	$(COMPOSE) build backend frontend
	$(COMPOSE) restart backend frontend

.PHONY: help env up down logs migrate makemigrations superuser shell sync-supabase test lint check
