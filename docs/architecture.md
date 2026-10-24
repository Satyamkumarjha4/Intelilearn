# Architecture

## What the product does

A learner signs in and asks to learn a topic. Lesson Crafter first **diagnoses** what they already know with a 10-question quiz across five difficulty bands. Depending on the result, it takes one of three paths:

- **Knows almost nothing** (0–2 correct by default): a 5-question prerequisite quiz, then a lesson that teaches the missing prerequisites first.
- **Knows some** (3–9 correct): a lesson pitched at their level.
- **Knows it all** (10/10): offers a cheat sheet, revision sheet, or practice sheet instead.

A **lesson** has four pages: Introduction (with prerequisites if needed), Core concepts, Advanced concepts, and a Test (10–15 questions of mixed types). The pages include interactive graphs, simulations, animations, and real images or GIFs. The content is validated against the learner's level, compiled into a TypeScript document, security-scanned, test-rendered in a headless sandbox, and only then shown.

The complete flow is in [lesson-graph.md](lesson-graph.md). The classes, layers and design patterns are in [design.md](design.md), and the test-driven workflow in [testing.md](testing.md).

## Components

```
                    ┌──────────────────────────────┐
  Browser ───────▶  │ Next.js (localhost:3000)     │   lesson renders in a sandboxed iframe
                    │  /api/* proxied to Django    │   (sandbox/ runtime)
                    └──────────────┬───────────────┘
                                   │ HTTP + SSE (JWT in httpOnly cookie)
                    ┌──────────────▼───────────────┐
                    │ Django + DRF (uvicorn, ASGI) │  auth, profile, lessons, quizzes,
                    │                              │  runs/SSE, signed media, admin
                    └──────┬──────────────┬────────┘
             enqueue       │              │ SUBSCRIBE run:{id}:events
                    ┌──────▼──────────────▼────────┐
                    │ Redis                        │  Celery broker/results, pub/sub,
                    │                              │  registry cache, rate-limit buckets
                    └──────┬───────────────────────┘
                           │
                    ┌──────▼───────────────────────┐        ┌──────────────────────────┐
                    │ Celery worker                │──SQL──▶│ Supabase Postgres        │
                    │  LangGraph flow per lesson   │        │  app tables              │
                    │  model gateway ──▶ LLM APIs  │        │  LangGraph checkpoints   │
                    │  media tools ──▶ Wikimedia,  │        └──────────────────────────┘
                    │                  Openverse   │
                    │  node sandbox/scripts:       │──▶ MEDIA_ROOT (local files)
                    │   check.mjs, render-check.mjs│
                    └──────────────────────────────┘
```

| Component | Responsibility |
|---|---|
| **Next.js** | UI. The stage-driven lesson page, quiz runner, study-sheet templates, and sandboxed lesson viewer. |
| **Django** | Auth and profile, lesson CRUD, quiz delivery and **synchronous grading**, resuming graphs, SSE progress, signed media URLs, and the admin (model registry and `FlowSettings`). It never calls an LLM inside a request. |
| **Celery worker** | Runs graph segments: start, resume after each learner input, retry, repair, grading. |
| **LangGraph** | One `StateGraph` thread per lesson with `interrupt()` pauses, parallel `Send` fan-outs, validation loops, targeted regeneration, and fallbacks. |
| **Model gateway** | Resolves the model chain for each node from the registry snapshot. Handles structured output, tool calling, reasoning settings, retries, fallback, rate limits, and call logging. |
| **`sandbox/`** | One JS package used in two places. It is the browser runtime inside the iframe, and it holds the backend's validation scripts (static and security scan, headless Playwright render check). |
| **Redis** | Celery broker and result backend, the progress pub/sub channel, the registry cache, and rate-limit token buckets. |
| **Postgres** | All application data **and** LangGraph checkpoints. It is the docker `db` service by default. When `SUPABASE_DATABASE_URL` is set it is **Supabase**, and local rows are copied up on each backend start (insert-only). Django connects over a normal Postgres connection. Supabase Auth, Storage, and the Data API are not used. |

### Why checkpoints live in Postgres, not Redis

The flow pauses for the learner at up to two `interrupt()` points, and a learner may come back hours or days later. Checkpoints must therefore be durable and must not expire. `langgraph-checkpoint-postgres` on the existing Supabase database provides that. Redis stays for short-lived data.

## Lifecycle

1. **Create.** `POST /api/lessons {topic}` creates a `Lesson`, snapshots the model registry and `FlowSettings`, and enqueues `start_flow`. It returns `{lesson_id, run_id}`, and the UI subscribes to `/api/runs/{run_id}/events`.
2. **Diagnose.** The graph generates and validates the diagnostic bundle, saves the `Quiz`, emits `awaiting_input`, and pauses at `interrupt()`. The worker is now free.
3. **Answer.** The learner submits. Django grades the answers with the shared pure function, stores a `QuizAttempt`, and returns the score immediately. It then enqueues `resume_flow(lesson_id, attempt_id)`, and the UI subscribes to the new run.
4. **Route.** The graph resumes from the checkpoint and takes one of three branches: mastery (another pause, for the sheet choice), prerequisite quiz (another pause), or directly to assessment.
5. **Author, build, and verify** (lesson path). Plan, write pages and test in parallel, plan interactives, run the media agent and widget code in parallel, alignment judge, compile pages in parallel, static and security checks, assemble, headless render check, targeted repairs, persist.
6. **Show.** On `done`, the UI loads `/api/lessons/{id}/document` and renders it in the sandboxed iframe.
7. **After.** The learner can take the page-4 test (graded by the `grade_test` graph), request more study sheets, or trigger an automatic runtime repair if the browser hits an error.

## Resilience layers

| Layer | Handles | Mechanism |
|---|---|---|
| Model gateway | Timeouts, 429, 5xx, schema parse failures, provider outages | Backoff retries, then the node's fallback chain |
| Graph | Wrong-but-parseable output, misaligned content, broken or unsafe code | `validate_*` nodes with conditional edges: retry with feedback, targeted regeneration with `Send`, degrade, fall back, fail |
| Task | Worker crash or timeout | `acks_late` redelivery, resume from the Postgres checkpoint |
| Browser | Runtime errors that the headless check missed | `runtime_repair` graph, capped per lesson |

## Security

- **Keys:** LLM and media API keys are in `backend/.env` only. The registry stores environment variable names.
- **Generated code** is untrusted, so it is contained in four ways:
  1. an AST security scan and scope allow-list before it is saved;
  2. a headless render with every network request blocked;
  3. an iframe with `sandbox="allow-scripts"` (opaque origin, no cookies);
  4. a strict CSP inside the iframe.
- **Media** is downloaded, sniffed, and size-checked, then served from our own server through signed URLs. Generated code cannot reference external URLs.
- **Answers** to quizzes and tests never reach the browser before the learner submits.
- **Supabase:** Django owns the tables. RLS is enabled with no policies on every table, including the checkpoint tables, so the public Data API exposes nothing.
