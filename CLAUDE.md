# Lesson Crafter: development instructions

An AI tutor that diagnoses what a learner knows, then generates a lesson or study sheet. The specification lives in `docs/`. Read the relevant doc before changing behaviour, and update it in the same change when behaviour changes. `docs/roadmap.md` tracks progress by phase: tick items off as they land.

## Stack and tooling (no substitutes)

- **Backend**: Django 5.2 + DRF + Celery in `backend/`, managed with **uv** (`uv add`, `uv run`). Never use pip or requirements files.
- **Frontend**: Next.js 16 in `frontend/`, managed with **bun** (`bun add`, `bunx`). Never use npm, yarn, or pnpm. Next 16 differs from older versions (for example, `middleware.ts` is now `proxy.ts`): follow `frontend/AGENTS.md` and check `frontend/node_modules/next/dist/docs/` before writing frontend code.
- **Running**: Docker Compose (`make up`). Services: `db` (Postgres), `redis`, `backend`, `worker`, `frontend`. `make help` lists every command.
- After adding a dependency, rebuild with `docker compose up --build`.

## Configuration

- **Every** port, host, name, password, key, and URL comes from the environment, through the single root `.env` (template: `.env.example`). This covers Django settings, `docker-compose.yml`, and `next.config.ts`.
- Every variable has a working development default, so the stack and tests run with no `.env` (CI). Use `env("X", default=...)` in Django and `${X:-default}` in compose.
- To add a variable: add it to `.env.example` with a comment, and to compose if containers need it. Never hard-code the value anywhere.
- Never print, log, or commit secrets. Don't read `.env` values into output; grep variable names only if needed. `.env` and `token` are gitignored.

## Database

- There is no Supabase URL by default, so the app uses the docker `db` Postgres. When `SUPABASE_DATABASE_URL` is set, Supabase becomes `default`, and on every backend start `manage.py bootstrap` migrates both databases and copies local rows that Supabase lacks. The copy is insert-only and never overwrites (`backend/core/sync.py`).
- Schema changes go through Django migrations only (`make makemigrations`). Never edit tables in the Supabase dashboard.
- Tests always run against the docker Postgres, never Supabase (`TESTING` in settings).

## LLM calls

- Never hard-code a model, provider, or parameter. Every LLM call goes through `llm_registry.gateway.Gateway().invoke(node_key, ..., snapshot=...)`, with a node key from `llm_registry/node_specs.py`.
- A new LLM step means a new `NodeSpec`, then `migrate` creates its config. Bind models in the admin or in `llm_registry/seed.py`.
- Tests use fake chat models, never real APIs (see `tests/llm_registry/conftest.py`).

## API conventions

- API paths have **no trailing slash** (`/api/lessons`). The Next.js `/api` proxy depends on it.
- Every endpoint has `@extend_schema` (tags, summary, request and response schemas), so Swagger at `/api/docs` stays accurate.

## Tests

- Tests live in the repo-root **`tests/`**, mirroring `backend/`. For example, `backend/core/sync.py` is tested in `tests/core/test_sync.py`, and `backend/config/databases.py` in `tests/config/test_databases.py`.
- Every change to backend behaviour comes with tests in the matching path. Mock external services (LLMs, media APIs); only `pytest -m live` may call them.
- **Before finishing any task, run `make check` (lint + tests) and report the actual result.** If something fails, say so and show the output. Never describe work as done while checks fail.

## Git

- Never commit directly to `main`. Branch per piece of work: `phase-<n>/<topic>` (for example `phase-1/auth`) or `fix/<topic>`.
- Use Conventional Commits: `feat(accounts): cookie JWT login`, `fix(sync): reset sequences`, `docs: …`, `test: …`, `chore: …`. Keep each commit to one logical change.
- Commit only when `make check` passes. CI (`docs/ci.md`) runs the same checks on every push: a failing push to `main` is **reverted automatically**, and a failing branch gets a `ci-failure` issue that closes when it goes green. So never push to `main` without a green `make check`.
- Never commit `.env`, `token`, keys, or generated media.
- Commit, push, or open PRs only when asked. Never force-push, rewrite pushed history, or skip hooks (`--no-verify`).

## Code style

- Python: ruff, line length 120 (`make lint`). Frontend: eslint and `tsc` (run with `next typegen` first).
- Match the surrounding code's naming, structure, and comment density. Comments explain *why*, not *what*.
