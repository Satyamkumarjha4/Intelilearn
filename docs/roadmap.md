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

**Done when:** you can bind `media.search` in the admin, and the admin refuses a model without tool calling. **Test model** reports each capability. `RegistryResolver().resolve()` reflects your edits. ✅ Verified in the admin: node chains and health, spec requirements, a vision-less model refused for `media.verify`, and Test model reporting a missing key. Live calls are untested until API keys are set.

## Phase 3: Async flow infrastructure and Stage A (diagnose)

- [x] `Lesson`, `Quiz`, `QuizAttempt`, `GraphRun`, `FlowSettings` (with `StageTransitions` and the owner-scoped queryset)
- [x] Celery (`start_flow`, `resume_flow`), Postgres checkpointer and `setup_checkpointer`, event publishing, SSE view
- [x] Graph: `load_context` → `generate_diagnostic` → `validate_diagnostic` → publish/await (interrupt) → grade → route → prerequisite publish/await/grade → `assess_learner`
- [x] Shared `graph/grading.py`; quiz endpoints (strip answers, synchronous grading, resume)
- [x] `manage.py flow ...` commands
- [x] Frontend: `/lessons`, `/lessons/new`, stage-driven page, `PipelineProgress`, `QuizRunner`, result card, review

**Done when:** you can take the diagnostic in the browser and be routed correctly for 0, 5, and 10 correct answers, the prerequisite quiz works, and a `LearnerAssessment` is saved. Restarting the worker while a lesson waits at a quiz loses nothing. ✅ Verified on a second stack with the fake LLM ([local-setup.md](local-setup.md#6-walk-through-the-app-without-api-keys)): in a real browser, quiz → score by band → review → model outage → Retry; over the API, 0, 5 and 10 correct each routed to prerequisite, lesson and mastery, the prerequisite quiz covering only the missed foundations; a worker restart while a quiz waited lost nothing. Until phases 4 and 5 land, a lesson that reaches `mastery` or `lesson` stops after the diagnostic (its exit is `END`), and live models are untested.

## Phase 4: Mastery path

- [x] `CheatSheet`, `RevisionSheet`, and `PracticeSheet` schemas; `study.generate`; validators
- [x] Choice interrupt and `study_material` graph for extra sheets
- [x] `StudyMaterialView` templates, practice-sheet grading, PDF export

**Done when:** 10/10 on the diagnostic leads to a choice, and all three sheets render. ✅ Verified in a real browser on the fake-LLM stack: 10/10 → choice → cheat sheet (KaTeX rendered, PDF downloaded and starts with `%PDF`) → revision and practice sheets requested later through the extra-sheet graph → practice answers checked and a solution revealed → the three tabs survive a reload. Not verified: sheet quality from real models, and the LaTeX validity check (it needs the Node sandbox from Phase 5; until then `SandboxRunner.latex` skips it with a log line).

## Phase 5: Stage B (author)

- [x] `lesson.plan` and validator; parallel `page.generate` ×3 and `test.generate` with targeted retries
- [x] `interactive.plan`; `interactive.generate` and `check_interactive` (needs `sandbox/scripts/check.mjs`)
- [x] Media subgraph: tools (Wikimedia, Openverse, optional Giphy), `submit_media`, download and store, `media.verify`, SVG fallback; `MediaAsset` and signed URLs
- [x] `alignment.judge` and targeted fixes routed with `Send`

**Done when:** `flow show` for "Binary search" and for "Asexual reproduction" shows 3 aligned pages, a mixed-type test, a stepping simulation for the first, and a real amoeba image or GIF (or an SVG fallback) for the second. ✅ Verified with the fake LLM and its fake media service (`flow start` → `flow answer --correct 5` → `flow show`): both lessons show three pages of three sections, a ten-question test with five types, and the alignment passed; Binary search has a stepping `simulation` for the core page, Asexual reproduction has a downloaded, stored, attributed image (a `MediaAsset`, served through a signed URL that a tampered signature cannot open). The generated widget code passes the real `check.mjs`. Not verified: content quality from real models, the real Wikimedia, Openverse and GIPHY services, and the vision check (`media.verify` stays optional and unbound until Phase 7). The lesson stops after the alignment judge (its stage stays `generating_lesson`) until Phase 6 builds the document.

## Phase 6: Stage C (build and verify) and the lesson viewer

- [x] `sandbox/` package: runtime, scope (Mafs, motion, KaTeX, Figure, Assessment…), `check.mjs`, `render-check.mjs`, fixtures
- [x] `page.compile` ×3, `code_fix_loop`, `assemble_document`, `render_check`, `repair_page`, `persist_lesson`
- [x] Frontend `LessonSandbox` (CSP, postMessage protocol) and `LessonViewer`
- [x] `runtime_repair` graph and `LessonVersion`

**Done when:** you can go from topic to a rendered four-page lesson in the browser. A known-malicious snippet is rejected by `check.mjs`, and a lesson broken on purpose is repaired. ✅ Verified on the offline fake-LLM stack with headless Chromium driving the real frontend: topic → diagnostic → a ready lesson whose four pages (Introduction, Core, Advanced, Test) render in the sandboxed iframe (`sandbox="allow-scripts"`), with the stored image loading through its signed URL and the standard layout and widgets in place; a snippet that calls `fetch` with `document.cookie` is rejected by `check.mjs` (`forbidden-global`, `no-url`); with an interactive broken on purpose in the stored code, the page reported the crash, `runtime_repair` ran all six nodes, the lesson went to version 2 with the SVG widget showing, and version 1 was kept with its reason. The walk-through found a real bug that the unit tests had missed (an error from an interactive's boundary carried no `codeVersion`, so the page never asked for the repair); it is fixed and the render check now enforces it. Not verified: pages and interactives written by real models (the fake compiles the standard layout and answers a repair with a plain diagram), and the visual quality of generated layouts.

## Phase 7: Test grading and hardening (still local)

- [x] `grade_test` graph (deterministic MCQ and numerical grading; `test.grade` for the rest), `TestSubmission`, `TestResultPanel`
- [x] Tracing (LangSmith or Langfuse callbacks in the gateway)
- [x] `ModelCall` dashboards in the admin; `diagnostic.review` and `media.verify` enabled by default and unable to fail a lesson (tuning against real models is still to do)
- [x] Free-tier load spreading: Groq (gpt-oss-120b and 20b) leads the light nodes, Gemini 3.5 Flash the big-output ones with Flash-Lite behind it, seeded per-model `rpm_limit`s, and a spent daily quota (429) falls over to the next model without retries
- [x] `seed_registry --profile cheap`: cheapest models at low effort, to validate the flow before tuning quality
- [x] Golden-topic live suite (`pytest -m live`; written and its checks tested offline, **not run**: it needs real API keys)

**Done when:** a submitted test is graded (instantly for multiple choice and numerical answers, through `test.grade` for the rest) and shown in the viewer; tracing can be switched on by environment; the admin shows cost and latency per node; the live suite exists and is excluded from `make check`. ✅ Verified on the offline stack with headless Chromium driving the real frontend: a ten-question test was submitted from the lesson; the six automatic marks appeared at once ("8 of 20 marks so far"), the four written answers were graded by the `grade_test` run and the card became complete (14 of 20, 70%, "Graded by AI" on those four, topics to revisit, model answers on request); with the fake model server missing the output, the same submission ended as "Grading stopped" with the readable reason and the automatic marks kept, and the next submission graded normally. Not verified: real models grading real answers, tracing against a real LangSmith or Langfuse account, the effect of enabling the quiz reviewer and the picture check on real lessons, and the live suite itself.

## Across phases: design alignment

- [x] Close the [refactor backlog](design.md#refactor-backlog) for phases 0–2: code brought in line with the object design (OOP, SOLID, the named patterns), each item behaviour-neutral with tests green before and after.
- [x] The backlog items for the lesson-flow code (`graph/`, `lessons/`) landed with Phases 3–6 (grading, validators, prompts, Stage A nodes and the flow builder in Phase 3; media in Phase 5; code generation, the build nodes and the document builder in Phase 6).
- [x] Every existing test file has the header from [testing.md](testing.md#31-the-file-header-required) (unit under test, why, use cases), and `tests/` is linted like the backend.

## Later (not now)

- Deployment (hosting, managed Redis, production settings, media on Supabase Storage)
- A circuit breaker per model
- Letting the learner redo the diagnostic after finishing a lesson, to measure progress
