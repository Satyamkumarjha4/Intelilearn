# Architecture

## What the product does

A learner signs in and asks to learn a topic. Socra first **diagnoses** what they already know with a 10-question quiz across five difficulty bands. Depending on the result, it takes one of three paths:

- **Knows almost nothing** (0–2 correct by default): a 5-question prerequisite quiz, then a lesson that teaches the missing prerequisites first.
- **Knows some** (3–9 correct): a lesson pitched at their level.
- **Knows it all** (10/10): offers a cheat sheet, revision sheet, or practice sheet instead.

A **lesson** has three pages: Introduction (with prerequisites if needed), Core concepts and Advanced concepts. The **test** (ten questions, marked as soon as it is handed in) is a separate screen of the app, not a page of the lesson, and can be taken again as often as the learner likes, with new questions each time. The pages include interactive graphs, simulations, animations, and real images or GIFs. The content is validated against the learner's level, compiled into a TypeScript document, security-scanned, test-rendered in a headless sandbox, and only then shown.

The complete flow is in [lesson-graph.md](lesson-graph.md). The classes, layers and design patterns are in [design.md](design.md), and the test-driven workflow in [testing.md](../process/testing.md).

## Components

```
                    ┌──────────────────────────────┐
  Browser ───────▶  │ Next.js (FRONTEND_PORT)      │   lesson renders in a sandboxed iframe
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
                    │ Celery worker                │──SQL──▶│ Postgres (db or Supabase)│
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
| **Next.js** | UI. The public landing page, sign-in and the five-step setup, the stage-driven lesson page (quick check, lesson book, one-attempt test, study sheets, sandboxed viewer), and the staff console (`/console`). A route guard (`proxy.ts`) reads marker cookies to pick the page; the API authorises everything. |
| **Django** | Auth and profile (with consent to the terms), the landing page's try-it question (`marketing`), first-topic suggestions for the setup (`onboarding`), the staff console API (`console`: usage, lesson runs, routing, learners, an audit entry for every change), lesson CRUD, quiz delivery and **synchronous grading**, resuming graphs, SSE progress, signed media URLs, and the admin (model registry and `FlowSettings`). It never calls an LLM inside a learner's request. The one exception is the staff console's model probe, which makes a few real provider calls and is limited to 20 seconds. |
| **Celery worker** | Runs graph segments: start, resume after each learner input, retry, repair, grading. |
| **LangGraph** | One `StateGraph` thread per lesson with `interrupt()` pauses, parallel `Send` fan-outs, validation loops, targeted regeneration, and fallbacks. |
| **Model gateway** | Resolves the model chain for each node from the registry snapshot. Handles structured output, tool calling, reasoning settings, retries, fallback, rate limits, and call logging. |
| **`sandbox/`** | One JS package used in two places. It is the browser runtime inside the iframe, and it holds the backend's validation scripts (static and security scan, headless Playwright render check). |
| **Redis** | Celery broker and result backend, the progress pub/sub channel, the registry cache, and rate-limit token buckets. |
| **Postgres** | All application data **and** LangGraph checkpoints. It is the docker `db` service by default. When `SUPABASE_DATABASE_URL` is set it is **Supabase**, and local rows are copied up on each backend start (insert-only). Django connects over a normal Postgres connection. Supabase Auth, Storage, and the Data API are not used. |

### Why checkpoints live in Postgres, not Redis

The flow pauses for the learner at up to two `interrupt()` points, and a learner may come back hours or days later. Checkpoints must therefore be durable and must not expire. `langgraph-checkpoint-postgres` on the app's own Postgres database provides that. Redis stays for short-lived data.

## Lifecycle

1. **Create.** `POST /api/lessons {topic}` first asks the **action gate** what the work costs: with credits on (the default since phase 10.9) the gate prices it, takes those credits out of the learner's wallet as a reserve, or answers `402 insufficient_credits` before anything exists. Then it creates a `Lesson`, snapshots the model registry and `FlowSettings`, and enqueues `start_flow`. It returns `{lesson_id, run_id}`, and the UI subscribes to `/api/runs/{run_id}/events`.
2. **Diagnose.** The graph generates and validates the diagnostic bundle, saves the `Quiz`, emits `awaiting_input`, and pauses at `interrupt()`. The worker is now free.
3. **Answer.** The learner submits. Django grades the answers with the shared pure function, stores a `QuizAttempt`, and returns the score immediately. It then enqueues `resume_flow(lesson_id, attempt_id)`, and the UI subscribes to the new run.
4. **Route.** The graph resumes from the checkpoint and takes one of three branches: mastery (another pause, for the sheet choice), prerequisite quiz (another pause), or directly to assessment.
5. **Author, build, and verify** (lesson path). Plan, write pages and test in parallel, plan interactives, run the media agent and widget code in parallel, alignment judge, compile pages in parallel, static and security checks, assemble, headless render check, targeted repairs, persist.
6. **Show.** On `done`, the UI loads `/api/lessons/{id}/document` and renders it in the sandboxed iframe.
7. **Credits follow the work.** A reserve is kept (committed) when its action reaches its completion point (the Quick check served, the lesson ready) and given back if the work fails or the learner presses Stop; Retry asks again as a resume, so nobody is charged twice. New accounts start with 30 credits that never expire, studying earns a daily credit and streak bonuses, and more can be bought (Stripe or Razorpay). Credits are added only from a signature-verified provider event, never from the browser's return to the site.
8. **After.** The learner can take the test (attempt 1 is the set the lesson was built with; every try after it gets new questions from the `question_bank` graph), take a quick quiz on the lesson, request more study sheets, or trigger an automatic runtime repair if the browser hits an error.

## Resilience layers

| Layer | Handles | Mechanism |
|---|---|---|
| Model gateway | Timeouts, 429, 5xx, schema parse failures, provider outages | Backoff retries, then the node's fallback chain |
| Graph | Wrong-but-parseable output, misaligned content, broken or unsafe code | `validate_*` nodes with conditional edges: retry with feedback, targeted regeneration with `Send`, degrade, fall back, fail |
| Task | Worker crash or timeout | `acks_late` redelivery, resume from the Postgres checkpoint |
| Browser | Runtime errors that the headless check missed | `runtime_repair` graph, capped per lesson |

## Security

- **Keys:** LLM and media API keys are in the root `.env` only (gitignored; `docker-compose.yml` passes it to the backend and worker). The registry stores environment variable names, never the keys.
- **Generated code** is untrusted, so it is contained in four ways:
  1. an AST security scan and scope allow-list before it is saved;
  2. a headless render with every network request blocked;
  3. an iframe with `sandbox="allow-scripts"` (opaque origin, no cookies);
  4. a strict CSP inside the iframe.
- **Media** is downloaded, sniffed, and size-checked, then served from our own server through signed URLs. Generated code cannot reference external URLs.
- **Answers** to quizzes and tests never reach the browser before the learner submits, and an attempt that is over cannot change (`attempt_sealed`).
- **Payments** are the one place money enters. The webhook is the only endpoint with no sign-in and no CSRF cookie: its signature is checked over the raw body before any database work, a replayed event takes effect once (a unique provider event id), the body is capped at 256 KB, and the amount and currency must match the order or nothing is granted. The browser's return from a provider grants nothing: the return page asks the server, which asks the provider. A live provider key without `PAYMENTS_LIVE_MODE=true`, or the fake gateway outside debug, stops the app at start. Card, bank and UPI details never reach Socra; refunds are made by staff through the provider and take back only unspent credits.
- **The console** answers `404` to anyone who is not staff, signed in or not, as if it did not exist, and every change made there leaves an audit entry. Provider keys are never serialised.
- **Cookies:** the session and the markers the route guard reads are httpOnly; the one cookie the page sets itself (`lc_setting_up`) is a hint with no authority.
- **Supabase:** Django owns the tables. Row-level security with no policies (so the public Data API exposes nothing) is the intended lock-down, but the script for it was skipped while the app runs on the local Postgres, so it is **not in place**. Enable it, including on the checkpoint tables, before pointing a Supabase project at this app.
