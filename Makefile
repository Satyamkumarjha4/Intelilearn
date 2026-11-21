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

test-full: db-test ## Run every test, including the one-time migration tests that `make test` skips (what CI runs)
	$(RUN_TEST_DB) pytest $(PYTEST_PARALLEL) -m 'not live and not payments_live'

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

lint: ## Lint backend (ruff, OpenAPI schema) and frontend (eslint, tsc, bun test); unit-test the e2e spec map (host bun)
	$(COMPOSE) run --rm --no-deps backend sh -c "ruff check $(RUFF_PATHS) && ruff format --check $(RUFF_PATHS) && python manage.py spectacular --validate --fail-on-warn --file /dev/null"
	$(COMPOSE) run --rm --no-deps frontend sh -c "bun run lint && bunx next typegen && bunx tsc --noEmit && bun test"
	@# The e2e spec map and its guard (no browser, no stack): a new spec or source folder nobody mapped fails here. Host bun: e2e/ is not in a container.
	cd e2e && bun test .test.ts

check: lint test ## Lint + tests (without the one-time migration tests): run at the end of a phase and before handing work back

check-full: lint test-full ## Lint + every test, as CI runs it

# --- Browser tests against the fake LLM (docs/process/testing.md) ---------------------------------------------------------
# Its own compose project, ports and database: no Supabase, no provider key, nothing shared with `make up`.
E2E_FRONTEND_PORT ?= 7100
E2E_BACKEND_PORT ?= 7110
E2E_STAFF_EMAIL ?= staff@example.com
E2E_STAFF_PASSWORD ?= E2e-staff-pass-1
# Workers for the specs that make their own learner (the others run first, alone); see e2e/support/phases.ts.
E2E_WORKERS ?= 4
# What `make e2e-affected` compares the working tree against.
BASE ?= main
E2E_COMPOSE := FRONTEND_PORT=$(E2E_FRONTEND_PORT) BACKEND_PORT=$(E2E_BACKEND_PORT) E2E_FRONTEND_PORT=$(E2E_FRONTEND_PORT) E2E_BACKEND_PORT=$(E2E_BACKEND_PORT) docker compose -p socra-e2e -f docker-compose.yml -f docker-compose.e2e.yml --profile e2e

fake-llm: ## Start the throwaway stack on a fake LLM (own database), with its registry and a staff user
	$(E2E_COMPOSE) up -d --build
	@echo "waiting for the API..."; for i in $$(seq 1 90); do curl -sf -o /dev/null http://localhost:$(E2E_BACKEND_PORT)/api/health && break; sleep 2; done; curl -sf -o /dev/null http://localhost:$(E2E_BACKEND_PORT)/api/health
	@# The API answering is not enough: a cold frontend once answered 500 on every page (next/font could not be resolved in its dev
	@# server) and `up` still reported success, so every spec then failed three minutes in. The first request compiles the page.
	@echo "waiting for the frontend..."; ok=; for i in $$(seq 1 60); do curl -sf -o /dev/null http://localhost:$(E2E_FRONTEND_PORT)/auth && ok=1 && break; sleep 3; done; \
	  [ -n "$$ok" ] || { echo "the frontend does not answer 200 on /auth: its dev server is broken. Run make e2e-down, then make fake-llm again."; exit 1; }
	$(E2E_COMPOSE) exec -T backend python manage.py seed_registry --file /tests/e2e/fake_registry.json
	$(E2E_COMPOSE) exec -T -e STAFF_EMAIL=$(E2E_STAFF_EMAIL) -e STAFF_PASSWORD=$(E2E_STAFF_PASSWORD) backend python manage.py shell -c "import os; from django.utils import timezone; from accounts.models import User; u, _ = User.objects.get_or_create(email=os.environ['STAFF_EMAIL'], defaults={'name': 'Staff'}); u.is_staff = True; u.email_verified_at = u.email_verified_at or timezone.now(); u.email_verification_source = u.email_verification_source or 'operator'; u.set_password(os.environ['STAFF_PASSWORD']); u.save()"
	@# This stack charges for real (docker-compose.e2e.yml), so a spec that builds several lessons for one learner would run out of the 30
	@# signup credits. The daily credit is made large here: it is earned by the first study, so the signup grant (30) that the credits specs
	@# read is untouched, and a learner is never short once they have studied. The dev defaults are not changed.
	$(E2E_COMPOSE) exec -T backend python manage.py shell -c "from credits.models import CreditSettings; s = CreditSettings.load(); s.daily_credits = 100000; s.save()"
	@echo "up: http://localhost:$(E2E_FRONTEND_PORT)  (staff: $(E2E_STAFF_EMAIL))"

e2e: fake-llm ## Run the Playwright smoke tests against the fake-LLM stack (first run: cd e2e && bun install && bunx playwright install chromium)
	cd e2e && E2E_COMPOSE="$(E2E_COMPOSE)" E2E_BASE_URL=http://localhost:$(E2E_FRONTEND_PORT) E2E_API_URL=http://localhost:$(E2E_BACKEND_PORT) E2E_STAFF_EMAIL=$(E2E_STAFF_EMAIL) E2E_STAFF_PASSWORD=$(E2E_STAFF_PASSWORD) E2E_WORKERS=$(E2E_WORKERS) bun run test

e2e-affected: ## Run only the e2e specs the change can touch, against BASE (default main), and say which and why (PLAN=1: print only)
	cd e2e && BASE="$(BASE)" E2E_COMPOSE="$(E2E_COMPOSE)" E2E_BASE_URL=http://localhost:$(E2E_FRONTEND_PORT) E2E_API_URL=http://localhost:$(E2E_BACKEND_PORT) E2E_STAFF_EMAIL=$(E2E_STAFF_EMAIL) E2E_STAFF_PASSWORD=$(E2E_STAFF_PASSWORD) E2E_WORKERS=$(E2E_WORKERS) bun affected.ts $(if $(PLAN),--plan)

probe-proxy: ## Send a forged X-Forwarded-For through the front door and say which address Django counts: make probe-proxy URL=https://your.site
	$(COMPOSE) exec backend python manage.py probe_forwarded_header $(if $(URL),--url $(URL))

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

# --- The pre-launch audit stack (docs/process/testing.md, "The audit stack") -----------------------------------------------
# Its own compose project (`socra-audit`), ports and database; the fake payment gateway, the outbox mailer and the
# stand-in Google in both modes; production throttles and prices. MODE=mock: the scripted fake LLM, which can be told to
# fail on cue. MODE=live: the real model keys in .env, on synthetic inputs, against LIVE_MAX_COST_USD.
MODE ?= mock
AUDIT_RUN ?= $(shell date +%F)
AUDIT_PROFILE ?= default
AUDIT_FRONTEND_PORT ?= 7200
AUDIT_BACKEND_PORT ?= 7210
AUDIT_FAKE_LLM_PORT ?= 7220
AUDIT_PERSONAS := docs/audit/$(AUDIT_RUN)/personas.local
AUDIT_FILES := -f docker-compose.yml -f docker-compose.audit.yml $(if $(filter mock,$(MODE)),-f docker-compose.audit-mock.yml --profile e2e)
AUDIT_COMPOSE := FRONTEND_PORT=$(AUDIT_FRONTEND_PORT) BACKEND_PORT=$(AUDIT_BACKEND_PORT) AUDIT_FRONTEND_PORT=$(AUDIT_FRONTEND_PORT) AUDIT_BACKEND_PORT=$(AUDIT_BACKEND_PORT) AUDIT_FAKE_LLM_PORT=$(AUDIT_FAKE_LLM_PORT) docker compose -p socra-audit $(AUDIT_FILES)

audit-up: ## Start the audit stack and seed its personas: make audit-up MODE=mock|live (AUDIT_RUN=YYYY-MM-DD, AUDIT_HISTORY=1 for live history)
	@case "$(MODE)" in mock|live) ;; *) echo "MODE must be mock or live (got '$(MODE)')"; exit 1;; esac
	@if [ "$(MODE)" = live ]; then \
	  have=""; for name in GEMINI_API_KEY GROQ_API_KEY; do grep -q "^$$name=." .env 2>/dev/null && have="$$have $$name"; done; \
	  [ -n "$$have" ] || { echo "MODE=live needs a model key in .env (GEMINI_API_KEY or GROQ_API_KEY)."; exit 1; }; \
	  echo "live: model keys present in .env:$$have; budget LIVE_MAX_COST_USD=$${LIVE_MAX_COST_USD:-2.00} (check: make audit-spend)"; \
	fi
	@# One shared password for every persona, made once per run and kept out of git. It is never printed.
	@mkdir -p docs/audit/$(AUDIT_RUN)
	@test -f $(AUDIT_PERSONAS) || { umask 077; pw=$$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 24); { echo "# Synthetic audit personas (audit-<name>@example.test). One shared password. Git-ignored: never paste it anywhere."; echo "AUDIT_PERSONA_PASSWORD=$$pw"; } > $(AUDIT_PERSONAS); }
	@export AUDIT_PERSONA_PASSWORD=$$(sed -n 's/^AUDIT_PERSONA_PASSWORD=//p' $(AUDIT_PERSONAS)); \
	  $(AUDIT_COMPOSE) up -d --build && \
	  echo "waiting for the API..." && ok=; for i in $$(seq 1 90); do curl -sf -o /dev/null http://localhost:$(AUDIT_BACKEND_PORT)/api/health && ok=1 && break; sleep 2; done; \
	  [ -n "$$ok" ] || { echo "the API did not answer: make audit-down, then try again."; exit 1; }; \
	  echo "waiting for the frontend..."; ok=; for i in $$(seq 1 60); do curl -sf -o /dev/null http://localhost:$(AUDIT_FRONTEND_PORT)/auth && ok=1 && break; sleep 3; done; \
	  [ -n "$$ok" ] || { echo "the frontend does not answer 200 on /auth: make audit-down, then try again."; exit 1; }; \
	  if [ "$(MODE)" = mock ]; then $(AUDIT_COMPOSE) exec -T backend python manage.py seed_registry --file /tests/e2e/fake_registry.json; \
	  else $(AUDIT_COMPOSE) exec -T backend python manage.py seed_registry --profile $(AUDIT_PROFILE); fi && \
	  $(AUDIT_COMPOSE) exec -T backend python manage.py audit_seed $(if $(filter live,$(MODE)),$(if $(AUDIT_HISTORY),,--skip-history)) && \
	  echo "audit stack up (MODE=$(MODE)): http://localhost:$(AUDIT_FRONTEND_PORT)  API http://localhost:$(AUDIT_BACKEND_PORT)/api/docs  personas: $(AUDIT_PERSONAS)"

audit-spend: ## What the live audit has spent on models, against LIVE_MAX_COST_USD (fails when over)
	$(AUDIT_COMPOSE) exec -T backend python manage.py audit_spend

audit-down: ## Stop the audit stack and delete its database (the personas file is kept)
	docker compose -p socra-audit -f docker-compose.yml --profile e2e down -v --remove-orphans

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

.PHONY: audit-up audit-down audit-spend help env up down logs migrate makemigrations superuser shell sync-supabase db-test test test-full test-serial test-for lint check check-full e2e e2e-affected beat-log
