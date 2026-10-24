# Roadmap

**Current goal: a complete project that runs locally.** Deployment is out of scope until that goal is met.

Each phase ends with something runnable and checkable.

## Phase 0: Scaffolding ✅

- [x] `backend/`: uv project, Django 5.2, DRF, drf-spectacular (Swagger UI `/api/docs`, ReDoc, schema), django-environ, Celery app, WhiteNoise
- [x] `core` app: `GET /api/health` (database, Redis, Celery worker) and the `core.tasks.ping` task; tests
- [x] `frontend/`: Next.js 16 with bun, Tailwind v4, `/api` rewrite to Django, home page with live system status
- [x] `docker-compose.yml` (db with a persistent volume, redis, backend, worker, frontend), dev Dockerfiles, hot reload everywhere
- [x] One root `.env` for all ports, hosts, names, passwords, and secrets, used by Django, compose, and Next.js, with defaults for everything (runs with no `.env`, for CI)
- [x] Database selection: docker Postgres by default; Supabase when `SUPABASE_DATABASE_URL` is set, with an insert-only local → Supabase sync on every start (`bootstrap`, `sync_to_supabase`)
- [x] Repo-root `tests/` mirroring `backend/`; tests always use the docker Postgres
- [x] `Makefile` (`check` = lint + test), `.gitignore`, `CLAUDE.md` development rules
- [x] GitHub Actions CI on every push: lint + tests; auto-revert failing pushes to `main`; `ci-failure` issue per failing branch, auto-closed when green

**Done:** `make up` starts the stack, and `/api/health` is `ok` both directly and through the Next.js proxy. Swagger UI loads, and a Celery task completes a round trip. `make check` passes, both with a `.env` and with none (a CI simulation on fresh volumes). The sync copies local rows to a stand-in Supabase database once and is a no-op on the next start.

## Phase 1: Foundation

- [ ] ~~Set `SUPABASE_DATABASE_URL`, verify the sync and `/api/health`~~ *(skipped for now: running on the local Postgres)*
- [x] `accounts`: `User` (email login, UUID key) and `Profile` (auto-created); cookie JWT auth with refresh rotation and blacklist; CSRF; auth rate limit; register/login/refresh/logout/me; profile GET/PUT/PATCH; admin
- [ ] ~~`scripts/enable_rls.sql`~~ *(skipped with Supabase)*
- [x] shadcn/ui (base-nova); `lib/api.ts` (CSRF, silent refresh, typed errors); `/auth`, `/onboarding`, `/profile`; header account menu; `proxy.ts` route guard
- [x] Tests in `tests/accounts/`; OpenAPI schema validated in `make lint` and CI

**Done when:** you can register, log in, complete onboarding, and see your user and profile in the admin. ✅ Verified in a real browser (register → onboarding → profile edit → sign out → guard → wrong password → sign in back to `?next`). The Supabase part is deferred.

## Phase 2: Model registry

- [x] `Provider`, `LLMModel` (with capabilities), `NodeConfig`, `NodeModelBinding`, `ModelCall`
- [x] `NODE_SPECS` (16 nodes) with `NodeConfig` rows created after migrate; capability, limit, and parameter validation in the admin
- [x] Resolver with Redis cache, cleared on every registry save; per-lesson snapshots
- [x] Gateway: structured output (`include_raw`, one in-place repair), tool calling, reasoning translation (parameter names verified per provider), retries with backoff and `Retry-After`, fallback chain, per-minute rate limiter, `ModelCall` logging with tokens and cost
- [x] **Test model** capability probes; `seed_registry`; `export_registry` and import; admin JSON export; grouped `manage.py check` warnings
- [x] Unit tests with fake chat models, and real clients built offline to verify parameter names

**Done when:** you can bind `media.search` in the admin, and the admin refuses a model without tool calling. **Test model** reports each capability. `resolve_registry()` reflects your edits. ✅ Verified in the admin: node chains and health, spec requirements, a vision-less model refused for `media.verify`, and Test model reporting a missing key. Live calls are untested until API keys are set.

## Phase 3: Async flow infrastructure and Stage A (diagnose)

- [ ] `Lesson`, `Quiz`, `QuizAttempt`, `GraphRun`, `FlowSettings`
- [ ] Celery (`start_flow`, `resume_flow`), Postgres checkpointer and `setup_checkpointer`, event publishing, SSE view
- [ ] Graph: `load_context` → `generate_diagnostic` → `validate_diagnostic` → publish/await (interrupt) → grade → route → prerequisite publish/await/grade → `assess_learner`
- [ ] Shared `graph/grading.py`; quiz endpoints (strip answers, synchronous grading, resume)
- [ ] `manage.py flow ...` commands
- [ ] Frontend: `/lessons`, `/lessons/new`, stage-driven page, `PipelineProgress`, `QuizRunner`, result card, review

**Done when:** you can take the diagnostic in the browser and be routed correctly for 0, 5, and 10 correct answers, the prerequisite quiz works, and a `LearnerAssessment` is saved. Restarting the worker while a lesson waits at a quiz loses nothing.

## Phase 4: Mastery path

- [ ] `CheatSheet`, `RevisionSheet`, and `PracticeSheet` schemas; `study.generate`; validators
- [ ] Choice interrupt and `study_material` graph for extra sheets
- [ ] `StudyMaterialView` templates, practice-sheet grading, PDF export

**Done when:** 10/10 on the diagnostic leads to a choice, and all three sheets render.

## Phase 5: Stage B (author)

- [ ] `lesson.plan` and validator; parallel `page.generate` ×3 and `test.generate` with targeted retries
- [ ] `interactive.plan`; `interactive.generate` and `check_interactive` (needs `sandbox/scripts/check.mjs`)
- [ ] Media subgraph: tools (Wikimedia, Openverse, optional Giphy), `submit_media`, download and store, `media.verify`, SVG fallback; `MediaAsset` and signed URLs
- [ ] `alignment.judge` and targeted fixes routed with `Send`

**Done when:** `flow show` for "Binary search" and for "Asexual reproduction" shows 3 aligned pages, a mixed-type test, a stepping simulation for the first, and a real amoeba image or GIF (or an SVG fallback) for the second.

## Phase 6: Stage C (build and verify) and the lesson viewer

- [ ] `sandbox/` package: runtime, scope (Mafs, motion, KaTeX, Figure, Assessment…), `check.mjs`, `render-check.mjs`, fixtures
- [ ] `page.compile` ×3, `code_fix_loop`, `assemble_document`, `render_check`, `repair_page`, `persist_lesson`
- [ ] Frontend `LessonSandbox` (CSP, postMessage protocol) and `LessonViewer`
- [ ] `runtime_repair` graph and `LessonVersion`

**Done when:** you can go from topic to a rendered four-page lesson in the browser. A known-malicious snippet is rejected by `check.mjs`, and a lesson broken on purpose is repaired.

## Phase 7: Test grading and hardening (still local)

- [ ] `grade_test` graph (deterministic MCQ and numerical grading; `test.grade` for the rest), `TestSubmission`, `TestResultPanel`
- [ ] Tracing (LangSmith or Langfuse callbacks in the gateway)
- [ ] `ModelCall` dashboards in the admin; `diagnostic.review` and `media.verify` tuned and enabled
- [ ] Golden-topic live suite

## Later (not now)

- Deployment (hosting, managed Redis, production settings, media on Supabase Storage)
- A circuit breaker per model
- Letting the learner redo the diagnostic after finishing a lesson, to measure progress
