# Plan: phases 3 to 7

Working plan for implementing roadmap phases 3 to 7. The specification stays in the docs it already lives in; this file records what each phase needs, in what order, what it touches, the ambiguities and how they were resolved, and how each phase is tested. Delete it when phase 7 is merged.

## 0. Starting point (measured on 2026-10-24)

- Branch `phase-3/lesson-flow`, which already holds three work-in-progress commits on top of `main`: the Django `lessons` app (models and migration `0001`), the Pydantic schemas for every LLM input and output, and a **function-based draft of the whole graph** (`graph/flow.py`, `graph/nodes/*`, `validators.py`, `prompts.py`, `codegen.py`, `media.py`, `sandbox.py`, about 3,700 lines). None of it has tests, and none of it follows the object model in [design.md](design.md) yet. It imports and builds (36 graph nodes), and `makemigrations --check` is clean.
- No `FlowRunner`, Celery tasks, event publisher, SSE, REST endpoints, admin, management commands or frontend pages exist for lessons. There is no `sandbox/` package and no Node in the backend image.
- Uncommitted: a `Makefile` change that adds `*-log` targets. It is the owner's work and is left untouched and uncommitted.
- Baseline before any change: `make check` is green. Backend 190 passed, frontend 21 passed, ruff, ruff format, OpenAPI validation, eslint and `tsc` clean.
- No LLM API keys and no Supabase URL are configured, so live-model behaviour cannot be verified here (see section 5).

## 1. Requirements and acceptance criteria per phase

Specs: [roadmap.md](roadmap.md) (checklists and "Done when"), [lesson-graph.md](lesson-graph.md) (graph behaviour), [data-model.md](data-model.md), [api.md](api.md), [frontend.md](frontend.md), [design.md](design.md) (binding object model), [testing.md](testing.md).

### Phase 3: async flow infrastructure and Stage A (diagnose)

Roadmap items: models; Celery `start_flow`/`resume_flow`, Postgres checkpointer, `setup_checkpointer`, event publishing, SSE; the Stage A graph; shared grading; quiz endpoints; `manage.py flow`; frontend `/lessons`, `/lessons/new`, the stage-driven page, `PipelineProgress`, `QuizRunner`, result card, review.

Acceptance (roadmap): the diagnostic can be taken in the browser and routes correctly for 0, 5 and 10 correct answers; the prerequisite quiz works; a `LearnerAssessment` is saved; restarting the worker while a lesson waits at a quiz loses nothing.

Verifiable form: graph tests with a scripted gateway for the three routes; a test that a second runner with a fresh graph object resumes a paused thread from the Postgres checkpoint; API tests for ownership (404), answer stripping, 400 on unanswered, 409 on repeat; a browser walk-through with a scripted gateway.

### Phase 4: mastery path

Roadmap items: `CheatSheet`/`RevisionSheet`/`PracticeSheet` schemas, `study.generate`, validators; choice interrupt and the `study_material` graph; `StudyMaterialView` templates, practice-sheet grading, PDF export.

Acceptance: 10/10 on the diagnostic leads to a choice, and all three sheets render.

### Phase 5: Stage B (author)

Roadmap items: `lesson.plan` and validator; parallel `page.generate` x3 and `test.generate` with targeted retries; `interactive.plan`; `interactive.generate` and `check_interactive` (needs `sandbox/scripts/check.mjs`); media subgraph (Wikimedia, Openverse, optional Giphy, `submit_media`, download and store, `media.verify`, SVG fallback), `MediaAsset` and signed URLs; `alignment.judge` with targeted fixes through `Send`.

Acceptance: `flow show` for "Binary search" and "Asexual reproduction" shows 3 aligned pages, a mixed-type test, a stepping simulation for the first and a real image/GIF (or SVG fallback) for the second.

Verifiable form: with scripted gateway output and `httpx.MockTransport` media sources, a graph run reaches Stage C input for both topics; the second topic exercises download/verify and the SVG fallback; `flow show` prints both.

### Phase 6: Stage C (build and verify) and the viewer

Roadmap items: `sandbox/` package (runtime, scope, `check.mjs`, `render-check.mjs`, fixtures); `page.compile` x3, `code_fix_loop`, `assemble_document`, `render_check`, `repair_page`, `persist_lesson`; frontend `LessonSandbox` (CSP, postMessage protocol) and `LessonViewer`; `runtime_repair` graph and `LessonVersion`.

Acceptance: topic to a rendered four-page lesson in the browser; a known-malicious snippet is rejected by `check.mjs`; a lesson broken on purpose is repaired.

### Phase 7: test grading and hardening

Roadmap items: `grade_test` graph (deterministic MCQ/numerical, `test.grade` for the rest), `TestSubmission`, `TestResultPanel`; tracing callbacks in the gateway; `ModelCall` dashboards in the admin; `diagnostic.review` and `media.verify` tuned and enabled; golden-topic live suite.

Acceptance: roadmap lists none; derived from the spec: a submitted test is graded (instantly for MCQ/numerical, through `test.grade` for the rest) and shown in the viewer; tracing can be switched on by environment; the admin shows cost and latency per node; the live suite exists and is excluded from `make check`.

## 2. Dependencies and implementation order

```
3 (models, runner, SSE, quiz API, Stage A, lessons UI)
 ├─ 4 (needs the runner, the choice interrupt and the lesson page)
 └─ 5 (needs the runner; the interactive check needs sandbox check.mjs)
      └─ 6 (needs Stage B output; builds the sandbox package)
           └─ 7 (needs the viewer, the Assessment UI and ModelCall data)
```

The order is 3 → 4 → 5 → 6 → 7. One cross-phase item: Stage B's `check_interactive` needs `sandbox/scripts/check.mjs`, which the roadmap lists under phase 5 and the viewer runtime under phase 6. The `check.mjs` half of the package is built in phase 5, the runtime and `render-check.mjs` in phase 6.

## 3. Files and modules each phase touches

| Phase | Backend | Frontend | Other |
|---|---|---|---|
| 3 | `lessons/` (services, querysets, `StageTransitions`, serializers, views, urls, admin, `flow` command), `graph/` (grading → `QuizGrader`/`RoutingPolicy`; validators for Stage A; prompts package; `Node` bases; Stage A nodes; `FlowGraphBuilder`; `FlowContext`/`EventSink`), `flow/` runner + tasks + publisher + SSE, `setup_checkpointer`, `config/urls.py`, settings | `/lessons`, `/lessons/new`, `/lessons/[id]`, `PipelineProgress`, `QuizRunner`, `QuizResultCard`, `RunEventStream`, `types.ts`, header link | docs: api, data-model, lesson-graph, local-setup, design, roadmap, testing |
| 4 | mastery nodes, `StudyMaterialValidator`, choice/material endpoints, `StudyMaterialGraphBuilder` | `MasteryChoice`, `StudyMaterialView` (3 templates), print stylesheet, PDF export | `bun add` KaTeX, PDF library |
| 5 | author nodes, `Plan/Page/FinalTest/InteractivePlan` validators, `MediaSource` classes, `MediaDownloader`, `LicensePolicy`, media subgraph, alignment router, `MediaUrlSigner` and `/api/media/{id}` | pipeline step grouping | `sandbox/` package with `check.mjs`; Node in the backend image |
| 6 | build nodes, `DocumentAssembler`, `CodeSanitizer`, `CodeFixLoopBuilder`, `RuntimeRepairGraphBuilder`, `LessonDocumentBuilder`, document/repair/versions endpoints | `LessonSandbox`, `SandboxBridge`, `LessonViewer`, toolbar | `sandbox/` runtime, scope, `render-check.mjs`, built bundle; Chromium in the worker image |
| 7 | `GradeTestGraphBuilder`, `TestSubmission`, grading service/endpoints, tracing `CallbackProvider` in the gateway, `ModelCall` admin dashboard, `diagnostic.review`/`media.verify` defaults, `tests/live/` | `TestResultPanel` | `.env.example`, docs |

## 4. Open ambiguities and how they were resolved

| # | Ambiguity | Resolution and reasoning |
|---|---|---|
| 1 | No base or integration branch was named. | The repo convention is one branch per phase (`phase-<n>/<topic>`), merged into `main` with a merge commit (see the history). Phase branches are stacked: `phase-3/lesson-flow` (existing, holds the draft), then `phase-4/mastery`, `phase-5/author`, `phase-6/build-verify`, `phase-7/grading-hardening`, each cut from the previous one. Nothing is pushed, because CLAUDE.md allows pushing only on request. **Outcome:** every check passed, but no integration branch was named and CLAUDE.md forbids commits to `main`, so nothing was merged: `phase-7/grading-hardening` contains the other four branches and is the integration candidate (merge it into `main` with a merge commit when you are ready; nothing was pushed). |
| 2 | The draft graph is function-based, but CLAUDE.md and design.md forbid new module-level logic and list its conversion in the refactor backlog "when you next touch that module". | Convert each module to the classes in design.md while writing its tests, one phase at a time (grading/validators/prompts/nodes/builders/context in phase 3, `media.py` in phase 5, `codegen.py` and `lessons/document.py` in phase 6). Behaviour stays as drafted unless a test shows a bug; each bug found gets a test first. Backlog rows are ticked as they close. |
| 3 | Where do the Celery tasks, runner and publisher live? design.md §4.10 names `FlowRunner`, `RedisEventPublisher`, `RunEventStream` but not a package. | A new Django app `flow` would add a migration-less app for no reason. They go in `lessons/` (`runner.py`, `events.py`, `tasks.py`, `streams.py`), the app that owns `GraphRun`. Recorded in design.md. |
| 4 | The checkpointer needs `langgraph-checkpoint-postgres` on the default database, which may be Supabase (session pooler). | `CheckpointerFactory` builds a `PostgresSaver` from the default database's connection settings, with a connection pool, using `autocommit=True` as the saver requires. Under tests, the same docker Postgres is used. `setup_checkpointer` is called from `bootstrap` so a fresh stack is ready. |
| 5 | `Command(resume=…)` payloads and the "restart the worker loses nothing" criterion. | Resume payloads are the attempt id (a string). Losing nothing is verified by a test that pauses a thread, builds a new runner with a new compiled graph and checkpointer, resumes, and reaches the end. A manual worker restart is also done in the walk-through. |
| 6 | The sandbox needs Node, and `render-check` needs headless Chromium. The backend image is `python:3.12-slim`. | Add Node 22 and Playwright's Chromium (with system libraries) to the backend image, and mount `./sandbox` into the backend and worker containers. The image grows by several hundred MB. The alternative (a separate sandbox service) adds an HTTP hop and a second image for no gain at this stage. `SandboxRunner.available()` already degrades gracefully and the graph reports a warning when the sandbox is absent. |
| 7 | The browser must run the *same* runtime the backend validates. | The runtime is built once from `sandbox/` with esbuild into `sandbox/dist/runtime.js`; the frontend serves a copy from `public/sandbox/` (generated, not committed) and `render-check.mjs` loads the same file. |
| 8 | Dependencies the frontend needs (KaTeX, a PDF library, sucrase, mafs, motion). | Added with `bun add`; the frontend image is rebuilt. Sandbox-only libraries are dependencies of `sandbox/`, not of `frontend/`. The sandbox package is managed with bun, like the frontend. |
| 9 | Tracing: "LangSmith or Langfuse". | A `CallbackProvider` Strategy on the gateway with `NoTracing` (default), `LangSmithTracing` (needs no new dependency; enabled by `LLM_TRACING=langsmith` plus the standard `LANGSMITH_*` variables) and `LangfuseTracing` (imports `langfuse` lazily and reports a clear error if it is missing). Keys come from the environment only. |
| 10 | Giphy is optional and needs a key. | `GiphySource` is only registered when `GIPHY_API_KEY` is set and `giphy` is in `FlowSettings.media_sources`. |
| 11 | `diagnostic.review` and `media.verify` "tuned and enabled". Without API keys, "tuned" cannot be measured. | They are enabled in `DefaultRegistry` with the chains already used for the neighbouring nodes, their prompts get tests for the failure modes they target, and the system check warns when they are unbound. Tuning against real models is listed as a known limitation. |
| 12 | The golden-topic live suite needs real keys. | Written under `tests/live/` with `@pytest.mark.live`, deselected by default, and reported as "not runnable here". |
| 13 | Supabase is not configured. | Not touched. Everything is tested on the docker Postgres, as CLAUDE.md requires. |

Nothing in the list changes the data model, a public API, or security behaviour beyond what the docs already specify, so no questions were needed.

## 5. Test strategy

All backend tests live in `tests/` mirroring `backend/`, each file with the header from [testing.md](testing.md), written before the code. Fakes, never real services: a `FakeGateway` with scripted outputs per node key (`tests/graph/conftest.py`), a fake `CodeSandbox`/`LatexChecker`, `httpx.MockTransport` for media, and a fake `EventPublisher`.

| Phase | Tests |
|---|---|
| 3 | `QuizGrader`/`RoutingPolicy` table-driven (0/2/3/9/10 correct, thresholds, don't-know, consistency); `DiagnosticValidator` one failing fixture per rule; `StageTransitions`; `LessonQuerySet.owned_by`; `Quiz.public_questions`; `LessonService`/`QuizService` with a fake runner (rows, snapshots, enqueue); views (401, 404 other user, 400, 409, answer stripping, schema); `FlowRunner` with a fake publisher; Stage A graph paths and interrupts with `Command(resume=…)`; checkpointer durability; SSE stream (snapshot, relay, terminal close); `flow` and `setup_checkpointer` commands. Frontend: `RunEventStream` and any new `lib/` class with `bun test`. |
| 4 | Study-sheet schema bounds, `StudyMaterialValidator` rules, mastery routing and choice interrupt, the extra-sheet graph, material endpoints (reveal logic for practice sheets, ownership, 409 on wrong stage), PDF/print helpers in `lib/`. |
| 5 | Plan/page/test/interactive-plan validators; targeted retry of one failed page; degrade paths; each `MediaSource` against recorded responses; license allow-list; sniffing, size and dimension limits; media subgraph paths (approved, rejected then retried, exhausted → SVG, tool-step cap); alignment recompute and `Send` only to flagged items; signed media URL sign/verify/expiry/tamper. Sandbox: `check.mjs` fixtures (good and malicious). |
| 6 | `CodeSanitizer`, `DocumentAssembler`, `code_fix_loop`, render-check decisions (pass, repair, fallback, fail), `persist_lesson`, `runtime_repair` graph with regression check and `LessonVersion`, document/repair/versions endpoints (stale `code_version` → 409, repair cap). Sandbox: `render-check.mjs` against good and deliberately broken lessons, network blocked. Frontend: `SandboxBridge` accepts only its iframe's messages. |
| 7 | Deterministic MCQ/numerical grading boundaries (tolerance, units, empty), `test.grade` fallback when the LLM fails, `TestSubmission` lifecycle, submission endpoints and ownership, tracing providers (selection, off by default, missing package), admin dashboard queries, live suite collected but deselected. |

Every phase ends with `make check` (ruff, ruff format, OpenAPI validation, eslint, `tsc`, `bun test`, pytest), plus `makemigrations --check`, plus a migrate-forward and backward run on a scratch database for any new migration. The final integration run repeats `make check` on the merged result and walks the critical journeys in a real browser with a scripted gateway.

## 6. Not verifiable in this environment

- Anything that needs a real model: output quality, prompt tuning, provider-specific structured-output behaviour, vision verification quality, tracing delivery to LangSmith or Langfuse.
- Real calls to Wikimedia, Openverse and Giphy.
- Supabase as the default database.

These are reported as "not runnable" in the final report, not as passed.
