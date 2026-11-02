# Socra

An AI tutor that first finds out what you already know, then teaches you the rest.

Ask for a topic ("binary search"). Socra gives you a 10-question diagnostic quiz across five difficulty bands. What happens next depends on how you did:

- **Little or nothing correct:** a short prerequisite check, then a lesson that teaches the missing foundations first.
- **Some correct:** a three-page lesson (Introduction · Core · Advanced, then a test you can retake with new questions) pitched at your level, with interactive graphs, simulations, animations, and real images or GIFs.
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

The docs index is [docs/README.md](docs/README.md). It lists every doc by job and flags the ones that are out of date.

**Getting started**

- [Local setup](docs/getting-started/local-setup.md): run everything on your machine

**Architecture**

- [Overview](docs/architecture/overview.md): what the product does, its components, and the lifecycle
- [Object design](docs/architecture/design.md): the rules, layers, patterns and class diagrams new code follows
- [Lesson flow graph](docs/architecture/lesson-graph.md): diagnose → author → build and verify, with every validation, retry, and fallback
- [Model registry](docs/architecture/model-registry.md): capabilities, node specs, reasoning, structured output, fallbacks, admin
- [Data model](docs/architecture/data-model.md): users, lessons, quizzes, media, runs, settings

**Reference**

- [API reference](docs/reference/api.md): REST and SSE
- [Frontend](docs/reference/frontend.md): stage-driven UI, quiz runner, study sheets, sandboxed lesson viewer
- [Onboarding topic suggestions](docs/reference/onboarding.md)

**Process**

- [Testing](docs/process/testing.md): how tests are written, and the browser tests (`make e2e`)
- [CI](docs/process/ci.md): checks on every push, auto-revert on main, failure issues for branches
- [Roadmap](docs/process/roadmap.md): build phases

**Archive**

- [UI audit, 25 October 2026](docs/archive/ui-audit-2026-10-25.md): the final screen-by-screen review against the mockups

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
make e2e      # browser tests on a throwaway stack with a fake LLM (docs/process/testing.md)
```

The app runs at http://localhost:3000 and Swagger at http://localhost:8000/api/docs (ports come from `.env`). It uses the docker Postgres until you set `SUPABASE_DATABASE_URL`. From then on, the backend copies local data up to Supabase on start. Details are in [docs/getting-started/local-setup.md](docs/getting-started/local-setup.md). Development rules are in [CLAUDE.md](CLAUDE.md).
