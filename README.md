# Socra

An AI tutor that first finds out what you already know, then teaches you the rest.

Ask for a topic ("binary search"). Socra gives you a 10-question diagnostic quiz across five difficulty bands. What happens next depends on how you did:

- **Little or nothing correct:** a short prerequisite check, then a lesson that teaches the missing foundations first.
- **Some correct:** a three-page lesson (Introduction · Core · Advanced, then a one-attempt final test) pitched at your level, with interactive graphs, simulations, animations, and real images or GIFs.
- **Everything correct:** you already know it, so you choose a **cheat sheet**, **revision sheet**, or **practice sheet**.

Every lesson is validated against your level, compiled to TypeScript, security-scanned, and test-rendered in a headless sandbox before you see it.

Socra (formerly Lesson Crafter) is a re-architecture of [girishkhanna1105/lessonCrafter](https://github.com/girishkhanna1105/lessonCrafter).

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (App Router, TypeScript, Tailwind v4, shadcn/ui), managed with **bun** |
| API | Django 5.2 + DRF on ASGI (uvicorn), managed with **uv**; Swagger UI via drf-spectacular |
| Database | PostgreSQL: docker Postgres locally, or **Supabase** when `SUPABASE_DATABASE_URL` is set (with automatic local → Supabase sync) |
| Orchestration | LangGraph: one stateful graph per lesson, with human-in-the-loop `interrupt()`s |
| Background jobs | Celery |
| Broker / pub-sub / cache | Redis |
| LLM access | A DB-backed **model registry** (provider, model, parameters, capabilities, fallbacks per node) edited in the Django admin |
| Structured output | Pydantic v2 schemas for every LLM input and output; `TypedDict` graph state |
| Local runtime | Docker Compose (db, redis, backend, worker, frontend); one root `.env` configures everything |
| Lesson sandbox | Shared `sandbox/` package: browser runtime plus static, security, and Playwright render checks |

## Documentation

1. [Architecture](docs/architecture.md): what the product does, its components, and the lifecycle
2. [Local setup](docs/local-setup.md): run everything on your machine
3. [Data model](docs/data-model.md): users, lessons, quizzes, media, runs, settings
4. [Model registry](docs/model-registry.md): capabilities, node specs, reasoning, structured output, fallbacks, admin
5. [Lesson flow graph](docs/lesson-graph.md): diagnose → author → build and verify, with every validation, retry, and fallback
6. [API reference](docs/api.md): REST and SSE
7. [Frontend](docs/frontend.md): stage-driven UI, quiz runner, study sheets, sandboxed lesson viewer
8. [Roadmap](docs/roadmap.md): build phases
9. [CI](docs/ci.md): checks on every push, auto-revert on main, failure issues for branches
10. [Testing](docs/testing.md): how tests are written, and the browser tests (`make e2e`)
11. [UI audit](docs/audit/ui-audit-2026-10-25.md): the final screen-by-screen review against the mockups

## Repository layout (target)

```
Lesson Crafter/
├─ docs/
├─ docker-compose.yml     # local stack
├─ docker-compose.e2e.yml # the throwaway fake-LLM stack for make e2e
├─ Makefile               # make up / check / test / lint / migrate …
├─ .env.example           # the single configuration template
├─ CLAUDE.md              # development rules (git, tests, config)
├─ tests/                 # backend tests, mirroring backend/
├─ .github/               # CI workflow + revert/issue scripts
├─ backend/                # Django (uv)
│  ├─ config/              # settings, urls, asgi, celery
│  ├─ core/                # health check, local → Supabase sync, bootstrap command
│  ├─ accounts/            # User, Profile, auth, consent
│  ├─ marketing/           # the landing page's try-it questions
│  ├─ onboarding/          # first-topic suggestions for the setup
│  ├─ console/             # the staff console API (usage, runs, routing, learners, audit)
│  ├─ llm_registry/        # registry models, node specs, resolver, gateway, reasoning
│  ├─ lessons/             # Lesson, Quiz, StudyMaterial, MediaAsset, GraphRun, API, SSE, tasks
│  └─ graph/               # state, schemas/, prompts/, nodes/, validators/, grading, media tools, graphs
├─ sandbox/                # lesson runtime + check.mjs + render-check.mjs (shared by frontend & backend)
├─ e2e/                    # Playwright smoke tests (make e2e), against a fake LLM
└─ frontend/               # Next.js (bun)
```

## Quick start

```bash
make env      # creates the single root .env from .env.example (optional: everything has defaults)
make up       # docker compose: db (Postgres), redis, backend, worker, frontend
make check    # lint + tests
make e2e      # browser tests on a throwaway stack with a fake LLM (docs/testing.md)
```

The app runs at http://localhost:3000 and Swagger at http://localhost:8000/api/docs (ports come from `.env`). It uses the docker Postgres until you set `SUPABASE_DATABASE_URL`. From then on, the backend copies local data up to Supabase on start. Details are in [docs/local-setup.md](docs/local-setup.md). Development rules are in [CLAUDE.md](CLAUDE.md).
