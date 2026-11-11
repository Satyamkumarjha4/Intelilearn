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

up: ## Build and start the stack (db, redis, backend, worker, beat, frontend)
	@# Remove the frontend container *with* its anonymous node_modules/.next volumes, so new packages are picked up.
	@# (--renew-anon-volumes would leave every old copy behind as a dangling volume.)
	$(COMPOSE) rm --force --stop --volumes frontend
	$(COMPOSE) up --build

down: ## Stop the stack and the test database (data volumes are kept)
	$(COMPOSE) --profile test down

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

# The suite runs in parallel (pytest-xdist) against a throwaway Postgres in memory (the `db-test` service), never Supabase and
# never the dev database. 8 workers is the best on a 12-core machine (12 was slower: the sandbox tests start browsers); CI
# uses `-n auto`. Override with `make test PYTEST_WORKERS=4`. `--dist worksteal` lets an idle worker take from a busy one.
PYTEST_WORKERS ?= 8
PYTEST_PARALLEL := -n $(PYTEST_WORKERS) --dist worksteal
RUN_TEST_DB := $(COMPOSE) run --rm -e POSTGRES_HOST=db-test backend

db-test: ## Start the in-memory Postgres the tests run on
	$(COMPOSE) up -d --wait db-test

test: db-test ## Run the test suite in parallel on the throwaway Postgres (PYTEST_WORKERS=8)
	$(RUN_TEST_DB) pytest $(PYTEST_PARALLEL)

test-serial: ## Run the test suite in one process on the dev Postgres: for debugging a failure the parallel run shows
	$(RUN_BACKEND) pytest

test-for: ## Run the tests of one file: make test-for FILE=backend/credits/ledger.py (or a tests/ path); frontend: bun test <file>
	@test -n "$(FILE)" || { echo "usage: make test-for FILE=backend/credits/ledger.py"; exit 1; }
	@f="$(FILE)"; \
	case "$$f" in \
	  tests/*) paths="/$${f}" ;; \
	  backend/*) rel=$${f#backend/}; paths=$$(ls tests/$$(dirname $$rel)/test_$$(basename $$rel .py)*.py 2>/dev/null | sed 's|^|/|' | tr '\n' ' ') ;; \
	  *) echo "FILE must be a backend/ or tests/ path (frontend files: cd frontend && bun test <file>)"; exit 1 ;; \
	esac; \
	[ -n "$$paths" ] || { echo "no test file mirrors $$f (looked for tests/<same path>/test_<name>*.py)"; exit 1; }; \
	echo "running $$paths"; \
	$(RUN_BACKEND) pytest -c pyproject.toml $$paths

lint: ## Lint backend (ruff, OpenAPI schema) and frontend (eslint, tsc, bun test)
	$(COMPOSE) run --rm --no-deps backend sh -c "ruff check $(RUFF_PATHS) && ruff format --check $(RUFF_PATHS) && python manage.py spectacular --validate --fail-on-warn --file /dev/null"
	$(COMPOSE) run --rm --no-deps frontend sh -c "bun run lint && bunx next typegen && bunx tsc --noEmit && bun test"

check: lint test ## Lint + tests: run before finishing any change

# --- Browser tests against the fake LLM (docs/process/testing.md) ---------------------------------------------------------
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
	@# This stack charges for real (docker-compose.e2e.yml), so a spec that builds several lessons for one learner would run out of the 30
	@# signup credits. The daily credit is made large here: it is earned by the first study, so the signup grant (30) that the credits specs
	@# read is untouched, and a learner is never short once they have studied. The dev defaults are not changed.
	$(E2E_COMPOSE) exec -T backend python manage.py shell -c "from credits.models import CreditSettings; s = CreditSettings.load(); s.daily_credits = 100000; s.save()"
	@echo "up: http://localhost:$(E2E_FRONTEND_PORT)  (staff: $(E2E_STAFF_EMAIL))"

e2e: fake-llm ## Run the Playwright smoke tests against the fake-LLM stack (first run: cd e2e && bun install && bunx playwright install chromium)
	cd e2e && E2E_COMPOSE="$(E2E_COMPOSE)" E2E_BASE_URL=http://localhost:$(E2E_FRONTEND_PORT) E2E_API_URL=http://localhost:$(E2E_BACKEND_PORT) E2E_STAFF_EMAIL=$(E2E_STAFF_EMAIL) E2E_STAFF_PASSWORD=$(E2E_STAFF_PASSWORD) bun run test

payments-live: ## Check each provider's real test mode that has keys in .env (no payment is made)
	$(RUN_BACKEND) pytest -m payments_live ../tests/payments/test_stripe_live.py ../tests/payments/test_razorpay_live.py -rs

e2e-payments: ## Pay through each provider's real test mode that has keys in .env (Stripe: sk_test_..., Razorpay: rzp_test_...)
	@ran=0; \
	if grep -q '^STRIPE_SECRET_KEY=sk_test_' .env 2>/dev/null; then $(MAKE) e2e-stripe && ran=1 || exit 1; fi; \
	if grep -q '^RAZORPAY_KEY_ID=rzp_test_' .env 2>/dev/null && grep -q '^RAZORPAY_KEY_SECRET=.' .env; then $(MAKE) e2e-razorpay && ran=1 || exit 1; fi; \
	[ $$ran = 1 ] || { echo "needs STRIPE_SECRET_KEY=sk_test_... or RAZORPAY_KEY_ID=rzp_test_... with RAZORPAY_KEY_SECRET in .env (docs/getting-started/local-setup.md)"; exit 1; }
	@echo "The stack was left with that provider as its only way to pay: run \`make fake-llm\` (or \`make e2e\`) to put the fake gateway back."

e2e-stripe:
	E2E_PAYMENT_GATEWAYS=stripe E2E_PAYMENT_DEFAULT=stripe $(MAKE) fake-llm
	cd e2e && E2E_STRIPE=1 E2E_COMPOSE="$(E2E_COMPOSE)" E2E_BASE_URL=http://localhost:$(E2E_FRONTEND_PORT) E2E_API_URL=http://localhost:$(E2E_BACKEND_PORT) bunx playwright test tests/payments-stripe.spec.ts

e2e-razorpay:
	E2E_PAYMENT_GATEWAYS=razorpay E2E_PAYMENT_DEFAULT=razorpay $(MAKE) fake-llm
	cd e2e && E2E_RAZORPAY=1 E2E_COMPOSE="$(E2E_COMPOSE)" E2E_BASE_URL=http://localhost:$(E2E_FRONTEND_PORT) E2E_API_URL=http://localhost:$(E2E_BACKEND_PORT) bunx playwright test tests/payments-razorpay.spec.ts

e2e-down: ## Stop the throwaway stack and delete its database
	$(E2E_COMPOSE) down -v

backend-log:
	$(COMPOSE) logs -f backend

frontend-log:
	$(COMPOSE) logs -f frontend

worker-log:
	$(COMPOSE) logs -f worker

beat-log:
	$(COMPOSE) logs -f beat

db-log:
	$(COMPOSE) logs -f db

redis-log:
	$(COMPOSE) logs -f redis

reload: #rebuilds backend and frontend
	$(COMPOSE) build backend frontend
	$(COMPOSE) restart backend frontend

.PHONY: help env up down logs migrate makemigrations superuser shell sync-supabase db-test test test-serial test-for lint check beat-log
