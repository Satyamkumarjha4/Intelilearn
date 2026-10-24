# Local setup

Everything runs locally with **Docker Compose**: Postgres, Redis, the Django API, the Celery worker, and the Next.js app. The Python backend is managed with **uv** and the frontend with **bun**. Deployment is out of scope.

## Prerequisites

| Tool | Why |
|---|---|
| Docker + Docker Compose v2 (2.24+) | Runs the whole stack |
| uv and bun *(optional on the host)* | Only needed to add dependencies or run tools outside Docker |
| A Supabase project *(optional)* | Hosted Postgres. Without it, the docker Postgres is used. |

## 1. Configure: one `.env` for everything

```bash
make env          # copies .env.example → .env (keeps an existing one)
```

The root `.env` is the **single source of configuration**. Django reads it, `docker-compose.yml` interpolates it, and `next.config.ts` loads it. Every variable has a development default, so the stack and the tests also run with **no `.env`** (this is what CI relies on).

| Group | Variables | Default |
|---|---|---|
| Host ports | `BIND_ADDRESS`, `BACKEND_PORT`, `FRONTEND_PORT`, `POSTGRES_PORT`, `REDIS_PORT` | 127.0.0.1 (not reachable from your LAN), 8000, 3000, 5432, 6379 |
| Django | `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `LOG_LEVEL` | dev key, false, localhost…, derived from ports, INFO |
| Auth | `JWT_ACCESS_MINUTES`, `JWT_REFRESH_DAYS`, `AUTH_COOKIE_SECURE` (also makes Django's session and CSRF cookies secure) | 30, 7, false |
| Rate limits | `AUTH_THROTTLE_RATE`, `AUTH_ACCOUNT_THROTTLE_RATE`, `AUTH_REFRESH_THROTTLE_RATE`, `TRUSTED_PROXY_COUNT` | 20/min, 10/min, 60/min, 1 |
| Local Postgres | `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | localhost, lessoncrafter ×3 |
| Supabase | `SUPABASE_DATABASE_URL`, `SYNC_LOCAL_TO_SUPABASE` | empty, true |
| Redis | `REDIS_HOST`, `REDIS_PASSWORD` | localhost, none |
| Frontend | `DJANGO_API_ORIGIN`, `NEXT_PUBLIC_BACKEND_URL` | `http://localhost:${BACKEND_PORT}` |
| LLM keys | `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` | empty. The default registry uses Gemini and Groq. |
| Reasoning budgets | `LLM_REASONING_BUDGET_LOW/MEDIUM/HIGH` | 2048 / 8192 / 24576 |

- The `POSTGRES_HOST`, `POSTGRES_PORT`, `REDIS_HOST`, and `REDIS_PORT` values in `.env` describe how the **host** reaches the services. Inside docker, compose overrides them with the service names and internal ports (`db:5432`, `redis:6379`).
- **Changing `POSTGRES_USER`, `POSTGRES_PASSWORD`, or `POSTGRES_DB` after the first start** has no effect on the existing `postgres-data` volume. Postgres only applies them when it initialises an empty volume. To apply new credentials to a volume holding nothing you need, run `docker compose down && docker volume rm lessoncrafter_postgres-data`. Otherwise, change them with SQL (`ALTER USER …`).

## 2. Run

```bash
make up            # = docker compose up --build
```

On start, `make up` also recreates the frontend's anonymous `node_modules` and `.next` volumes (removing the old ones), so new packages are picked up. On start, `backend` runs `manage.py bootstrap`: it migrates the active database, first syncing to Supabase when that's configured (see below). Code changes reload automatically: uvicorn `--reload` for the API, `watchfiles` for the Celery worker, and Turbopack for Next.js. Postgres and Redis data persist in the `postgres-data` and `redis-data` volumes.

| URL | What |
|---|---|
| `http://localhost:${FRONTEND_PORT}` | App. The home page shows live status for database, Redis, and worker, fetched through the `/api` proxy. |
| `http://localhost:${BACKEND_PORT}/api/docs` | **Swagger UI** |
| `http://localhost:${BACKEND_PORT}/api/redoc` | ReDoc |
| `http://localhost:${BACKEND_PORT}/api/schema` | OpenAPI 3 schema (YAML; add `Accept: application/json` for JSON) |
| `http://localhost:${BACKEND_PORT}/api/health` | Health JSON (`200` ok, `503` degraded) |
| `http://localhost:${BACKEND_PORT}/admin/` | Django admin (run `make superuser` first) |

## 3. Databases: local Postgres and Supabase

| `SUPABASE_DATABASE_URL` | `default` database | What happens on backend start |
|---|---|---|
| empty | docker `db` | `migrate` |
| set | Supabase | Migrate the local `db`, migrate Supabase, then **copy local rows Supabase doesn't have** |

About the sync (`backend/core/sync.py`, also available as `make sync-supabase`):

- **Insert-only.** It copies rows whose primary key is missing on Supabase. It never updates or deletes, so data created directly in Supabase is never overwritten. It is safe to run on every start.
- Models are copied in dependency order. Links to content types, permissions, and other models with natural keys are resolved by natural key. Many-to-many links travel with each newly copied object.
- A row that clashes on a unique field (for example, the same email under another id) is skipped and reported as a conflict. It doesn't stop the sync.
- Primary-key sequences on Supabase are reset afterwards.
- Content types, permissions, sessions, and admin log entries are not copied: `migrate` creates the first two, and the last two are ephemeral.
- Set `SYNC_LOCAL_TO_SUPABASE=false` to skip it.

Getting the Supabase URL: in the dashboard, go to **Connect** and copy the **Session pooler** string (port 5432). Append `?sslmode=require`. Do **not** use the transaction pooler (6543): Django, and later the LangGraph checkpointer, need session features.

**Lock down the Data API** after migrations that add tables: run `backend/scripts/enable_rls.sql` in the Supabase SQL editor (added in Phase 1). It enables RLS with no policies, so the public Data API can read nothing. Django connects as `postgres` and bypasses RLS.

## 4. Model registry (once)

```bash
docker compose exec backend python manage.py seed_registry   # Gemini + Groq defaults; a no-op if already seeded
docker compose exec backend python manage.py check           # warns about nodes without a usable model or API key
docker compose exec backend python manage.py probe_models    # real calls: every bound model, each declared capability
docker compose exec backend python manage.py probe_models --node learner.assess   # plus one call through a node's chain
```

`probe_models` exits non-zero when a check fails, and API keys never appear in its output.

Tune models, fallbacks, and parameters in the admin under **LLM model registry**. Share a tuned setup with `manage.py export_registry --output registry.json` and `seed_registry --file registry.json`. See [model-registry.md](model-registry.md).

## Everyday commands

```bash
make help            # list everything
make logs            # follow all logs
make migrate / makemigrations / superuser / shell
make sync-supabase   # run the local → Supabase copy manually
make test            # pytest (always the docker Postgres, never Supabase)
make lint            # ruff + eslint + tsc
make check           # lint + test: run before finishing any change
make down            # stop; volumes are kept
```

## Tests

- Tests live in the repo-root `tests/` folder, **mirroring `backend/`**: `backend/core/sync.py` is tested in `tests/core/test_sync.py`.
- The pytest config is in `backend/pyproject.toml` (`testpaths = ["../tests"]`). In docker, `tests/` is mounted at `/tests`.
- Under pytest, settings ignore `SUPABASE_DATABASE_URL`. Two test databases are created on the docker Postgres: `default` and `local`. The second one exists so the sync can be tested between two real databases.
- **CI:** `docker compose run --rm backend pytest` needs no `.env`. Everything falls back to defaults.

## Adding dependencies

```bash
cd backend && uv add <package>     # updates pyproject.toml + uv.lock
cd frontend && bun add <package>   # updates package.json + bun.lock
docker compose up --build          # rebuild images
```

The backend image installs into `/opt/venv`, outside the bind-mounted `/app`. The frontend keeps `node_modules` in an anonymous volume. Host copies never clash with the container's.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Permission denied` on `/app` (Fedora and other SELinux hosts) | Bind mounts use the `:z` label. Keep it. |
| `port is already allocated` | Change the port in `.env`. |
| `password authentication failed` after editing `POSTGRES_*` | The volume keeps its original credentials. See section 1. |
| Health: `celery: no workers responded` | `docker compose logs worker`. It restarts on file changes, so check for a Python error. |
| New dependency not found | `docker compose up --build`. |
| `no space left on device` from Docker while `df` shows free space (btrfs) | Metadata is full and there's no unallocated space for more. Run `sudo btrfs balance start -dusage=20 /` (then `-dusage=50`) to give empty data chunks back, and `docker volume prune` for old anonymous `node_modules` volumes. |

## Later phases add

- `sandbox/` package: Node and Playwright Chromium in the backend image.
- `manage.py setup_checkpointer` for the LangGraph Postgres checkpoint tables.
- The `manage.py flow ...` commands.
