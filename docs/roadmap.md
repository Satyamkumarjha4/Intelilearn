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

## Across phases: the final test on its own screen, taken once

- [x] Backend and API: the generated document has the three content pages only; `GET /lessons/{id}/test` serves the test without answers; one submission per lesson (unique constraint, `409 already_submitted`); `regrade` for a failed grading; `GET …/test/submission`; `test_status` and `test_score` on the lesson; `has_embedded_test` on the document for older lessons; quiz review confirmed to carry everything. Frontend types and API client updated.
- [x] Lesson workspace shell: header with breadcrumb and journey stepper, `?tab=` tabs for a ready lesson, the redesigned building screen with "Your starting point", the friendly failed card, `loading.tsx`, `not-found.tsx`, `error.tsx`, and a `Dialog` primitive that replaces `window.confirm`.
- [x] Lesson viewer as a notebook with index flaps; the document's own navigation and the test page of older lessons are hidden by the runtime.
- [x] Flashcard deck for the quick check and the final test (forward only, resumes after a refresh); the Test tab takes the test once.
- [x] Read-only test results and quick check answers views.
- [x] "My lessons" (continue card, filter chips, status pills, delete in a dialog) and "New lesson" redesigned.
- [x] Five-step setup and the single-page profile, with the same tiles.
- [x] Backend: `POST /onboarding/topic-suggestions` (curated catalogue, `onboarding.suggest_topics` as the fallback and for translation); the setup's last step is built against the request and answer shapes of `backend/onboarding` (see docs/frontend.md).
- [ ] Removing the iframe `test_submit` path (nothing sends it any more).

## Across phases: the public landing page

- [x] `/` for signed-out visitors, built from the mockup's screen 11: hero with a try-it question, "How it works" walkthrough, "Three ways forward" carousel, proof strip, call to action and footer; scroll reveal and reduced-motion handling; `RouteGuard` sends signed-in visitors on; the system-status widget and the Swagger/admin links are gone from public UI.
- [x] Read `socra.pendingTopic` back on the screens after sign-up (it stays until the setup ends, so a refresh on the last step keeps it), and write `/privacy` and `/terms`.

## Across phases: landing page, second pass

- [x] Hero question bank: `marketing.DemoQuestion` (admin with subject, band and active filters), 25 seeded questions, `GET /api/landing/demo-question` (public, 60 a minute, never cached); a different question on every load, "Try again" flips to another, the built-in question when the API fails.
- [x] "How it works": the stage is as tall as the step list, caption top-left, preview under it.
- [x] "Your score decides" carousel autoplays every 6 s with a progress bar, pausing on hover, keyboard focus, touch and off screen (`Autoplay`).

## Across phases: onboarding topic suggestions (backend)

- [x] `GET /api/profile/options` (every choice list with its label); `Profile.preferred_language` has choices and `notes` a 2000-character limit, with a migration that fits existing rows (unknown language becomes English, long notes are cut).
- [x] `POST /api/onboarding/topic-suggestions`: four first topics from a curated catalogue (Classes 6 to 12, five field families at two levels, professional, interview and self-learner lists), with rule-built reasons, paging, and a per-learner throttle ([onboarding.md](onboarding.md)).
- [x] Node `onboarding.suggest_topics` (optional, seeded for speed): a model for a field the catalogue does not know, and one batched translation for other languages; Redis cache (30 days); any failure gives the English catalogue (`source: fallback`), never a `5xx`.
- [ ] Frontend: read `title_en` and `source` where they are useful; bind the node in an existing registry (admin, or `seed_registry --force` on an untuned one).

## Across phases: the staff console API

The backend of an in-app admin ("Socra Console"), replacing the Django admin for the everyday jobs. The design is [design.md §4.16](design.md#416-console-the-staff-api) and the endpoints are in [api.md](api.md#console-staff-only).

- [x] App `console`: staff-only access (404 for anyone else), a `120/min` throttle per staff member, `AuditEntry` and `AuditTrail`, `is_staff` on `/auth/me`.
- [x] `overview`: health with worker count, lessons, spend against `CONSOLE_MONTHLY_BUDGET_USD`, calls, daily spend by provider, funnel, slowest steps and four attention rules.
- [x] `usage` and `usage/export.csv`: KPIs, per model and per step with `percentile_cont`; one definition of ok, retried, failed and fallback (`CallOutcomes`); `ModelCall` indexed on `(model_name, created_at)` and `(node_key, created_at)`; `ModelCall.rate_limit_wait_ms`.
- [x] `runs`: list, detail with a timeline (`GraphRun.node_timings`, written by `GraphRunRecorder`) and the last 20 calls, retry and cancel through the learner's own services.
- [x] `providers` and `models`: list, change, add, delete (409 naming the steps), and a 20-second test that keeps `LLMModel.last_probe_*`.
- [x] `nodes` and `profiles`: grouped routing, atomic validated replace, profile preview; seed profiles `balanced` and `quality` next to `cheap`.
- [x] `flow-settings` with the admin form's validation and the routing thresholds (`RoutingPolicy.thresholds`); read-only `learners`; `audit`.
- [x] `lib/types.ts` and `lib/console-api.ts` (typed client).
- [x] The console UI, built from `docs/design/mockups/socra-admin-mockup.html`, screen by screen:
  - [x] Lesson runs (`/console/runs`: filters in the address, detail with timeline and model calls, Retry, Stop, live updates; [frontend.md](frontend.md#console-lesson-runs-consoleruns))
  - [x] The shell (access check, sidebar, query client), Overview and Usage & cost ([frontend.md](frontend.md#console-shell-overview-and-usage--cost-console))
  - [x] Models, Model routing and Lesson settings ([frontend.md](frontend.md#console-models-model-routing-and-lesson-settings-consolemodels-consolerouting-consolesettings))
  - [x] Learners and Change log ([frontend.md](frontend.md#console-learners-and-change-log-consolelearners-consoleaudit))
- [ ] Apply a profile in one request (today a screen would preview it and save each changed step with `PUT /console/nodes/{key}`), and a pause or an alert on the monthly budget.
- [ ] Tighten `FlowSettings.clean()` (the final test's minimum above its maximum, unknown media sources and licences are accepted by the admin and so by the console).

## Final UI wrap-up (audit and fixes)

The audit is in [audit/ui-audit-2026-10-25.md](audit/ui-audit-2026-10-25.md).

- [x] Stop, then Retry always picks the lesson up from its checkpoint (it was a no-op that left the lesson failed); the stop dialog is tied to the learner, not the run.
- [x] Refresh on the last onboarding step, `?next=` kept through sign-in and onboarding, no 401s on public pages, status pill from the pages read, loading and error states, print-safe landing page.
- [x] Browser tests in `e2e/` (`make e2e`) on a throwaway fake-LLM stack.
- [ ] Run `make e2e` in CI (needs a browser in the workflow).

## Later (not now)

- Deployment (hosting, managed Redis, production settings, media on Supabase Storage)
- A circuit breaker per model
- Letting the learner redo the diagnostic after finishing a lesson, to measure progress
