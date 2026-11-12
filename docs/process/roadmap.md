# Roadmap

**Current goal: a complete project that runs locally.** Deployment is out of scope until that goal is met. Phases 0 to 9 are built (phase 9, the modular lesson parts, is closed: see [phase 9](#phase-9-modular-lesson-parts) and the [spec](../architecture/modular-lessons.md)). Phase 10 (credits and payments) has begun: see [phase 10](#phase-10-credits-and-payments). What is left is the [open work](#open-work) below.

Each phase ended with something runnable and checkable. Every phase was verified on the offline fake-LLM stack (`make fake-llm`, see [local-setup.md](../getting-started/local-setup.md#6-walk-through-the-app-without-api-keys)), driving the real frontend in a headless browser where it applied. Real models (Gemini and Groq) have been tried end to end only a few times, so lesson quality and the tuning of the registry for real models are still open.

Tick items off as they land (a `CLAUDE.md` rule).

## Open work

Items carried over from the phases below, plus gaps found since. Nothing here blocks running the app locally.

**Privacy and security**

- [x] Delete a lesson's LangGraph checkpoints and its `ModelCall` rows together with the lesson (`LessonErasure`). See [data-model.md](../architecture/data-model.md#deleting-a-lesson).
- [x] The same clean-up for a user removed by hand (there is no self-service account deletion): done in phase 10.3 as `AccountErasure` (`manage.py erase_account`), which anonymises the account in place and erases everything the learner made, checkpoints and `ModelCall` rows included. A user with a wallet can no longer be deleted by hand at all (the credit tables protect it). See [data-model.md](../architecture/data-model.md#deleting-a-lesson).
- [x] Make the per-address rate limits independent of a client-supplied `X-Forwarded-For` (phase 11.0): the `/api` proxy forwards the last entry (or the Nth from the right, `EDGE_PROXY_HOPS`), never the client's first; measured on the real stack. **Still true:** with nothing in front of Next, a single forged header picks the address, so a deployment needs an edge that overwrites or appends, and `check --deploy` fails (`core.E002`) until `TRUSTED_PROXY_COUNT` is set on purpose. After a deploy, `make probe-proxy URL=<the site>` tries a forged header through the real front door and says which address Django counted. See [api.md](../reference/api.md).
- [ ] `scripts/enable_rls.sql`: row-level security with no policies on every table, including the checkpoint tables, for use with Supabase *(skipped while running on the local Postgres)*.
- [ ] Set `SUPABASE_DATABASE_URL`, then verify the sync and `/api/health` *(skipped while running on the local Postgres)*.

**Product rules**

- [x] Server-side enforcement of the one-question-at-a-time rule for the test: done in phase 9.2 (an answer is saved and locked on the server as the card is left, an attempt that is over cannot change, and a test can be retaken).

**Quality of generated lessons**

- [x] Run the live suite (`pytest -m live`) and record what it finds: done in phase 9.8, see [the results](#phase-98-live-suite-results). Tuning the registry for real models is still open, and the changes the run suggests are listed there for a decision.

**Credits and payments (left after phase 10)**

- [ ] **Phase 11, sign-in methods, blocks public launch** (D15): until accounts are verified, each unverified account gets 30 free credits.
- [ ] **Two-factor sign-in for staff accounts** (decided 2026-11-12, S3 of [the sign-in plan](../to_be_developed/signin-implementation-plan.md)): staff never sign in with Google or get linked to it (`REFUSE_STAFF`), so their password is the only door to the console; a second factor is a later phase, not Phase 11.
- [ ] Run the live checks with fresh test keys: `make payments-live` and `make e2e-payments` (Stripe's test key supplied for 10.7 was expired; Razorpay's were never supplied). The selectors in the two browser specs for the providers' own pages are unverified.
- [ ] Re-check Stripe's India onboarding and the RBI card rules before launch (D20); Razorpay is a configuration change if Stripe is not available. Decide the default gateway at launch.
- [ ] A first real webhook test on a public address (a tunnel or staging) for each provider; until then the return page and the five-minute sweep settle payments.
- [ ] GST registration and invoicing (D17): prices are tax-inclusive and the provider's receipt is the invoice for now.
- [ ] Have a lawyer review the Terms and Privacy Policy before the public sees them (the owner's note in [legal/README.md](../legal/README.md)), now that they cover payments and credits.
- [ ] A shortfall (a refund of credits already spent) is only listed; it has no "resolved" state or action.
- [ ] `StripeApi` and `RazorpayApi` repeat their transport code: extract a shared `ProviderApi` ([design.md refactor backlog](../architecture/design.md#refactor-backlog)).
- [ ] The Next.js proxy and rate limits behind a real host: the webhook throttle is per client address (`PAYMENT_WEBHOOK_THROTTLE_RATE`), which is only as good as the address the proxy forwards (the open item under Privacy and security).

**Features and cleanups**

- [ ] Remove the iframe `test_submit` path (nothing sends it any more).
- [ ] Frontend: read `title_en` and `source` of the topic suggestions where they are useful; bind the `onboarding.suggest_topics` node in an existing registry (admin, or `seed_registry --force` on an untuned one).
- [ ] Console: apply a profile in one request (today a screen previews it and saves each changed step with `PUT /console/nodes/{key}`), and a pause or an alert on the monthly budget.
- [ ] Tighten `FlowSettings.clean()` further: unknown media sources and licences are still accepted by the admin and so by the console. (Since phase 9.2 it refuses a Fail line at or above the Excellent line and a batch size outside 5 to 10; the test-size settings it used to leave unchecked were dropped in phase 9.8.)
- [ ] Run `make e2e` in CI (needs a browser in the workflow).

## Phases

### Phase 0: Scaffolding ✅

- [x] `backend/`: uv project, Django 5.2, DRF, drf-spectacular (Swagger UI `/api/docs`, ReDoc, schema), django-environ, Celery app, WhiteNoise
- [x] `core` app: `GET /api/health` (database, Redis, Celery worker) and the `core.tasks.ping` task; tests
- [x] `frontend/`: Next.js 16 with bun, Tailwind v4, `/api` rewrite to Django, home page with live system status
- [x] `docker-compose.yml` (db with a persistent volume, redis, backend, worker, frontend), dev Dockerfiles, hot reload everywhere
- [x] One root `.env` for all ports, hosts, names, passwords, and secrets, used by Django, compose, and Next.js, with defaults for everything (runs with no `.env`, for CI)
- [x] Database selection: docker Postgres by default; Supabase when `SUPABASE_DATABASE_URL` is set, with an insert-only local → Supabase sync on every start (`bootstrap`, `sync_to_supabase`)
- [x] Repo-root `tests/` mirroring `backend/`; tests always use the docker Postgres
- [x] `Makefile` (`check` = lint + test), `.gitignore`, `CLAUDE.md` development rules
- [x] GitHub Actions CI on every push: lint + tests; auto-revert failing pushes to `main`; `ci-failure` issue per failing branch, auto-closed when green

Done: `make up` starts the stack, `/api/health` is `ok` directly and through the proxy, and `make check` passes with and without a `.env`.

### Phase 1: Foundation ✅

- [x] `accounts`: `User` (email login, UUID key) and `Profile` (auto-created); cookie JWT auth with refresh rotation and blacklist; CSRF; auth rate limit; register/login/refresh/logout/me; profile GET/PUT/PATCH; admin
- [x] shadcn/ui (base-nova); `lib/api.ts` (CSRF, silent refresh, typed errors); `/auth`, `/onboarding`, `/profile`; header account menu; `proxy.ts` route guard
- [x] Tests in `tests/accounts/`; OpenAPI schema validated in `make lint` and CI
- The two Supabase items from this phase are in [open work](#open-work).

Done: register, sign in, complete onboarding, edit the profile, sign out, and be redirected by the guard.

### Phase 2: Model registry ✅

- [x] `Provider`, `LLMModel` (with capabilities), `NodeConfig`, `NodeModelBinding`, `ModelCall`
- [x] `NODE_SPECS` (16 nodes) with `NodeConfig` rows created after migrate; capability, limit, and parameter validation in the admin
- [x] Resolver with Redis cache, cleared on every registry save; per-lesson snapshots
- [x] Gateway: structured output (`include_raw`, one in-place repair), tool calling, reasoning translation (parameter names verified per provider), retries with backoff and `Retry-After`, fallback chain, per-minute rate limiter, `ModelCall` logging with tokens and cost
- [x] **Test model** capability probes; `seed_registry`; `export_registry` and import; admin JSON export; grouped `manage.py check` warnings
- [x] Unit tests with fake chat models, and real clients built offline to verify parameter names

Done: bind `media.search` in the admin, and the admin refuses a model without tool calling; **Test model** reports each capability.

### Phase 3: Async flow infrastructure and Stage A (diagnose) ✅

- [x] `Lesson`, `Quiz`, `QuizAttempt`, `GraphRun`, `FlowSettings` (with `StageTransitions` and the owner-scoped queryset)
- [x] Celery (`start_flow`, `resume_flow`), Postgres checkpointer and `setup_checkpointer`, event publishing, SSE view
- [x] Graph: `load_context` → `generate_diagnostic` → `validate_diagnostic` → publish/await (interrupt) → grade → route → prerequisite publish/await/grade → `assess_learner`
- [x] Shared `graph/grading.py`; quiz endpoints (strip answers, synchronous grading, resume)
- [x] `manage.py flow ...` commands
- [x] Frontend: `/lessons`, `/lessons/new`, stage-driven page, `PipelineProgress`, `QuizRunner`, result card, review

Done: 0, 5 and 10 correct answers route to the prerequisite quiz, the lesson and the mastery choice; a worker restart while a quiz waits loses nothing.

### Phase 4: Mastery path ✅

- [x] `CheatSheet`, `RevisionSheet`, and `PracticeSheet` schemas; `study.generate`; validators
- [x] Choice interrupt and `study_material` graph for extra sheets
- [x] `StudyMaterialView` templates, practice-sheet grading, PDF export

Done: 10/10 on the diagnostic leads to a choice, and all three sheets render. The LaTeX validity check needs the Node sandbox from Phase 5 (it skips with a log line without it).

### Phase 5: Stage B (author) ✅

- [x] `lesson.plan` and validator; parallel `page.generate` ×3 and `test.generate` with targeted retries
- [x] `interactive.plan`; `interactive.generate` and `check_interactive` (needs `sandbox/scripts/check.mjs`)
- [x] Media subgraph: tools (Wikimedia, Openverse, optional Giphy), `submit_media`, download and store, `media.verify`, SVG fallback; `MediaAsset` and signed URLs
- [x] `alignment.judge` and targeted fixes routed with `Send`

Done: three aligned pages, a mixed-type test, a stepping simulation and a stored, attributed image (or an SVG fallback), with media served through signed URLs a tampered signature cannot open.

### Phase 6: Stage C (build and verify) and the lesson viewer ✅

- [x] `sandbox/` package: runtime, scope (Mafs, motion, KaTeX, Figure, Assessment…), `check.mjs`, `render-check.mjs`, fixtures
- [x] `page.compile` ×3, `code_fix_loop`, `assemble_document`, `render_check`, `repair_page`, `persist_lesson`
- [x] Frontend `LessonSandbox` (CSP, postMessage protocol) and `LessonViewer`
- [x] `runtime_repair` graph and `LessonVersion`

Done: topic to a rendered lesson in the sandboxed iframe; a known-malicious snippet is rejected by `check.mjs`; a lesson broken on purpose is repaired and the earlier version is kept.

### Phase 7: Test grading and hardening ✅

- [x] `grade_test` graph (deterministic MCQ and numerical grading; `test.grade` for the rest), `TestSubmission`, `TestResultPanel`
- [x] Tracing (LangSmith or Langfuse callbacks in the gateway)
- [x] `ModelCall` dashboards in the admin; `diagnostic.review` and `media.verify` enabled by default and unable to fail a lesson
- [x] Free-tier load spreading: Groq (gpt-oss-120b and 20b) leads the light nodes, Gemini 3.5 Flash the big-output ones with Flash-Lite behind it, seeded per-model `rpm_limit`s, and a spent daily quota (429) falls over to the next model without retries
- [x] `seed_registry --profile cheap`: cheapest models at low effort, to validate the flow before tuning quality
- [x] Golden-topic live suite (`pytest -m live`; written and its checks tested offline, **not run**: it needs real API keys, see [open work](#open-work))

Done: a submitted test is graded (instantly for multiple choice and numerical answers, through `test.grade` for the rest), and a grading failure keeps the automatic marks and gives a readable reason.

### Phase 8: The UI wrap-up ✅

The final screen-by-screen review is kept in [../archive/ui-audit-2026-10-25.md](../archive/ui-audit-2026-10-25.md).

- [x] Stop, then Retry always picks the lesson up from its checkpoint; the stop dialog is tied to the learner, not the run
- [x] Refresh on the last onboarding step, `?next=` kept through sign-in and onboarding, no 401s on public pages, status pill from the pages read, loading and error states, print-safe landing page
- [x] Browser tests in `e2e/` (`make e2e`) on a throwaway fake-LLM stack

### Phase 9: Modular lesson parts ✅

Specified in [modular-lessons.md](../architecture/modular-lessons.md) and planned in [modular-lessons-implementation-plan.md](../archive/modular-lessons-implementation-plan.md) (phase details in its §14). Tick items off as they land.

- [x] 9.0 Prepare, with no visible change:
  - [x] Pure `Level`, `StarRating`, `RaterCategory`, `Difficulty`, `BandDifficulty`, `ScoreBand` and `Thresholds` classes (not wired in yet)
  - [x] `RunSubject` port and `GraphRun.subject`; the runner, `StopPoint`, `has_active_run`, the dispatcher, `LessonService.cancel` and the console runs list read it *(the `GraphRun.quick_quiz` foreign key and a nullable `lesson` wait for 9.6)*
  - [x] `ModelCall.quiz_id`
  - [x] Delete clean-up: checkpoints and model calls go with the lesson
  - [x] The metering seam: `ActionGate`, `OpenGate`, `ActionRefused`, completion points, settlement, resume-on-Retry, `IdempotencyStore` and the `Idempotency-Key` header; wired for `lesson.create`, `lesson.continue` and `sheet.generate`
  - [ ] Decisions answered and the mockup extended with the new screens
- [x] 9.1 `QuestionTypes` (neutral), then five-level `Difficulty` and its migration, marks, MSQ, expressions, criteria; levels renamed behind a `level_scheme` marker; the question-input registry (MSQ checkboxes, number input) in the frontend
- [x] 9.2 Question record, fixed 10-question objective test, attempts graded at submit, retakes (always generate, `test.retake`), trend, forward-only on the server
- [x] 9.3 Self-rating entry, `AssessmentSources`, lesson shapes, verified `origin`, the two-option mastery choice (Expert lesson or two sheets):
  - [x] `AssessmentSources` (`DiagnosticSource`, `SelfRatingSource`), `LessonShape` for the four levels, `EntrySegment` (entry router, `assess_from_source`, level gate, `prerequisites.plan`, intent router), `ChoiceRouter` and the two-sheet `SheetsSegment`
  - [x] `Lesson` columns `intent`, `origin`, `recommended_from`, `entry`, `level_source`, `self_rating_halves` (1 to 10 check), and `mastery_options` (so a lesson waiting at the old choice keeps its cards; dropped again in phase 9.8)
  - [x] `POST /lessons` takes `entry`, `self_rating`, `intent` and a server-verified `origin`; `POST /lessons/{id}/choice` takes `{choice}`
  - [x] `manage.py stranded_threads` lists (and with `--mark-failed` ends) lessons stuck at a node a release removed; Cancel on the "getting your questions ready" state
  - [x] New-lesson toggle and `StarRating`, journey and starting-point variants, `MasteryChoice` with two options, "Basics first", one handler for a refused action
- [x] 9.4 Follow-up lessons and the pop-up policy:
  - [x] `FollowupPolicy` (pure; the spec's six worked examples are its test table), the rater category (stars, or the level of the lesson), `AttemptOutcome` runs it on the submit path and the legacy `grade_test` path
  - [x] `Lesson.created_from_lesson` and `followup_level` with the one-per-level constraint; `FollowupService` and `POST /lessons/{id}/followups` (`lesson.followup` through the gate, `409 already_exists` with the lesson id, a real two-thread race test); deterministic names; `FollowupSource`
  - [x] `FollowupDialog`, the inline note for a low rater, links both ways on the lesson page; console funnel `retested` and `followups_started`
  - [x] From the 9.3 report: the "Basics check" copy, `seed_registry` binding nodes that have no binding, `entry` in the lesson list
- [x] 9.5 Modular sheets, any ready lesson, once per kind (`409` on repeat), no versions:
  - [x] `POST /lessons/{id}/materials` takes `kind` or `kinds` for any ready lesson (one run, one `sheet.generate`; `409 already_exists` with the kinds that exist, nothing made or asked); `GET` lists `[{kind, created_at}]`; no practice sheet can be asked for
  - [x] One `SheetsSegment` for the mastery choice, `intent=sheets` lessons (quick check or rating, any score, no prerequisite quiz and no choice) and extra sheets on a ready lesson; sheets rest on the lesson, the quiz's concepts, or the topic and level
  - [x] Metering hints for sheets (`sheets`, `grounding`, `choice: sheets_only`); `Lesson.sheets_only`; a follow-up refuses a sheets-only parent and carries the parent's note
  - [x] New-lesson screen asks "A lesson" or "Study sheets" (and which); a Study sheets tab on every ready lesson with "Add both sheets"; a sheets-only lesson's own tabs, journey and pill
  - [x] Root cause of the two stale-stage fixes: Retry restores a stage only when the thread is at a question (`StopPoint`), one correction fewer in `Node.__call__`
- [x] 9.6 Quick quiz: presets, calibration, up to 10 sources, difficulty mix, graphs, screens, code editor:
  - [x] Decisions from the 9.5 report: only lessons with pages are quiz sources; the revision-sheet coverage rule kept; "Finish your test first" on the Study sheets tab during an attempt
  - [x] `quizzes` app (`QuickQuiz`, `QuickQuizSource`, `QuickQuizAttempt`), abstract `GradableAttempt`, `GraphRun.quick_quiz` and a nullable `lesson` with the exactly-one constraint, flow settings and throttles, quiz deletion erases everything
  - [x] `DifficultyMix`, presets and kinds by topic, `SourceSplit` and `ConceptSummaries`, `AdaptiveLadder`, the three new assessment sources
  - [x] `topic.traits`, `quick_quiz` graph with calibration, `GradeAttemptGraphBuilder` as `grade_test` and `grade_quiz` over `AttemptStore`, retakes with an exclusion list
  - [x] Endpoints, leak tests, `quiz.create` and `quiz.retake` through the gate, create-a-lesson-from-a-result, console runs and usage by quiz
  - [x] `/quizzes`, `/quizzes/new`, `/quizzes/[id]`, calibration runner, results with recommendations, CodeMirror editor, header link
- [x] 9.7 Concept tags, recommendations, deep links:
  - [x] Decisions from the 9.6 report: page links replace the lesson-level ones; old lessons are backfilled once (`backfill_concept_index`, idempotent, `--dry-run`) with a lazy fallback for what it cannot place; the revision-sheet coverage rule is unchanged
  - [x] `Section.concepts` filled by `page.generate` and checked by `PageValidator`; `Lesson.concept_index` (migration 0017) written by `persist_lesson` through `ConceptIndex`
  - [x] Quiz summaries read the index (the plan for a lesson without one); every lesson-sourced question set (test, retake, quiz from lessons) is concept-bounded (`QuestionConcepts`, prompt lists, validator)
  - [x] Deterministic recommendations with a page link per weak concept (`ConceptLinks`), for quiz results and, in the same change, for a lesson test's topics to revisit (`revisit_links`); a deleted lesson says so
  - [x] `?tab=lesson&page=<key>` opens the book at that page; "Study this" links; e2e journey
- [x] 9.8 Retire and harden:
  - [x] Live suite: pure quality checks (`QuestionChecks`, `ConceptChecks`, `PoolChecks`, `TraitChecks`, `PlanChecks`, `DedupeChecks`, `SheetChecks`) with offline tests, `test_golden_questions.py`, run against the real models ([results](#phase-98-live-suite-results)); it found a crash in the review fix step (a test question the test does not have), fixed with a test
  - [x] `Lesson.final_test` replaced by the lesson's first set on the record (`Question.first_set_position`, migrations 0018 to 0020): every lesson keeps its test, tested on old-shape rows; `final_test_min`/`final_test_max` dropped
  - [x] The combined `POST /lessons/{id}/test/submissions` call, `submit_once`, `AlreadySubmitted` and the `test_submit` throttle removed
  - [x] The old three-sheet choice retired (nobody waiting at it: migration 0021 drops `mastery_options`, refusing to run if anyone does); the single-sheet nodes, the old cards and the frontend's single-sheet steps removed; `stranded_threads` finds nothing
  - [x] An old lesson's free-text test concepts are linked to the nearest plan concept (`ConceptIndex.nearest`, no model call)
  - [x] `backfill_concept_index` documented as a post-migrate deploy step; migrations read and write the database they run on
  - [x] e2e covers every journey of plan §15.4 (the retest's "getting your questions ready" wait is now asserted); the copy audit found no retired phrase; [pending-screens.md](../design/pending-screens.md) lists the screens for a design session
  - [x] Docs: spec and plan moved out of `to_be_developed/` (`architecture/modular-lessons.md`, `archive/modular-lessons-implementation-plan.md`), every doc of plan §17 updated, the copy rule in `CLAUDE.md` names "Quick quiz"

Phase 9 is closed. What it leaves open is in the [open work](#open-work) above and in the [live suite results](#phase-98-live-suite-results) below.

### Phase 9.8 live suite results

Run by hand on 2 November 2026 with `GEMINI_API_KEY` and `GROQ_API_KEY` set (the default registry: Gemini first, Groq as the fallback): five runs, two of them the whole suite, the others one file or one test after a fix to the suite's own code; nothing was skipped. The first run found the Gemini free tier's limit of about 20 requests a day for a model already used up, which made later calls fail with `429`; the later runs had quota back but met rate limits on both providers. A paid key removes that noise. **No product threshold was changed.**

| Check | Result |
|---|---|
| `topic.traits` judges quadratic equations and kinematics as calculation, Python list comprehensions as programming, the French Revolution as neither | **Pass** (3 of 3 runs that reached it) |
| `lesson.plan` sets `quantitative` for solving quadratic equations and not for the French Revolution | **Pass** (3 of 3) |
| The calibration pool has two valid multiple-choice questions in each of the five bands | **Pass** (3 of 3) |
| A 10-question quiz of every kind the topic offers: every kind is there; multiple-select questions have two or more right options; numerical expressions evaluate to their stored answer; short and long criteria add up to their marks (first try and retake) | **Pass** (2 of 2 runs that reached it; the first run's test was a harness slip, fixed) |
| A retake does not repeat the first try, even in other words | **Fail** (2 of 2): 1 to 2 questions a time share 64% to 71% of their words with an earlier one, generic stems such as "What is the degree of a quadratic equation?" and "Find the larger solution to the quadratic equation $x^2 - 7x + 10 = 0$." The product's own check drops a question at 80%, so these stay |
| On a real lesson (a self-rating of Binary search): its test and a quiz made from it name only the lesson's own concepts, the concept index places every concept on a page, the quiz is well formed, the revision sheet covers the concepts by the product's rule | **Pass**, twice: 10 of 10 concepts placed, the sheet mentioned 10 of 10 (a third attempt, in the whole-suite run, hit the crash below) |
| The golden topics (Binary search, Asexual reproduction, Photosynthesis) from a quick check to a ready lesson and a graded test | **Fail** (0 of 3 in both whole-suite runs) |

Why the golden topics failed, from the logs:

- **The quick check did not pass its own validator in 5 of 6 tries.** `diagnostic.generate` is allowed two attempts and the model repeated the same mistake: "options must all be different" for one to three questions (4 times), and "question q4 reveals the answer to q2" (once). Groq's `gpt-oss-120b` also answered with invalid JSON once, and was rate limited the rest of the time, so the fallback did not help.
- **One lesson did get built** (Asexual reproduction, in the first run, before the quick check failed on retry). It failed two checks: the test had two kinds of question (the harness wanted three; a non-quantitative lesson test is multiple choice and multiple select only, D15, so the harness was wrong and is fixed), and it had no real picture (the media search found none).
- **A real crash.** In the second whole-suite run the review judge flagged a test question that the test does not have, and the fix step looked it up with `next(...)` and failed the whole build with `RuntimeError: generator raised StopIteration`. Fixed in this phase (`AlignmentPolicy.fixable` now drops issues for questions that do not exist), with a test that fails without the fix.

Changes the run suggests, for you to decide (none is made):

1. **`diagnostic.generate`: allow three attempts, or say it in the prompt.** Raise `max_attempts` from 2 to 3 for that step in the registry, and add one sentence to the prompt: "the four options must all be different, and no question may name the answer to another". It is the step most likely to stop a learner before they have a lesson.
2. **Retake dedupe: lower `QuestionDeduper.NEAR` from 0.8 to about 0.65**, or also compare the options. At 0.65 the repeats above are caught; the risk is rejecting genuinely different questions that share a template, which the extra round of batches would write again (a cost, not a failure).
3. **Rate limits on the fallback.** Both providers throttled during a lesson build. A paid Gemini key, or a third model in the chain, would stop the quick check failing for lack of an answer.
4. **Media for biology topics.** "Asexual reproduction" found no picture. If a picture is wanted, the media agent's query or its sources need a look; the golden topic keeps `wants_picture` so the next run says.

To repeat the run: set `GEMINI_API_KEY` (and `GROQ_API_KEY` for the fallback) in `.env`, then `docker compose run --rm backend pytest -c pyproject.toml --rootdir=. /tests/live -m live -rA -s`. It costs a few dollars on a paid key and about 15 minutes.

### Live suite follow-ups (branch `fix/live-suite-findings`)

Decisions taken on the findings above, and what a sixth live run showed.

1. **`diagnostic.generate` gets three attempts** (`NodeSpec.default_max_attempts=3`, so every seeded profile has it; tests on the spec and on all four profiles) and its prompt now says it twice: the four options of every question, the prerequisite questions too, must differ in meaning, and no question's wording or options may give away the answer to another (tests on the exact text, with and without the prerequisite half). A registry that already exists keeps the 2 it was created with until `seed_registry --force`, or the admin, changes it: no migration rewrites a value someone may have tuned.
2. **`QuestionDeduper.NEAR` stays at 0.80: the change to 0.60 was not made, because it flags questions that are not repeats.** Measured with the product's own word overlap: 0.60 would call different questions the same in 4 of 7 pairs that a learner would call different: "What is a quadratic equation?" and "What is the discriminant of a quadratic equation?" (0.62), "What is the degree of …?" and "What is the discriminant of …?" (0.78), "Solve $x^2 - 5x + 6 = 0$." and "Solve $x^2 - 7x + 10 = 0$." (0.69) and "… $x^2 + 2x - 8 = 0$." (0.69). The pairs that share only the topic's words ("What is binary search?" and "Why does binary search need a sorted list?", 0.20) are safe at 0.60; the trouble is a shared question frame and the shape of a sum. Removing the frame words from the comparison fixes one of the four and leaves the sums at 0.69. A guard test now pins the seven pairs as "kept", so a future change to the threshold cannot flag them unnoticed. **Proposed fix, for a decision:** compare content words only (drop the frame: what, is, the, of, which, following, …), use 0.60 only when both questions have at least ten such words and keep 0.80 for shorter ones, and never call two questions near repeats when each holds a different `$…$` expression. On the pairs measured (the six reworded repeats are built to look like the live ones, since the live run only logged one side of each) this catches five of the six and keeps all seven different pairs; the sixth, "What is the degree of a quadratic equation?" against "What is the degree of the polynomial in a quadratic equation?", scores 0.75 on content words and stays under the line. It needs its own tests.
3. **No product change beyond decision 1.** The suite's own checks are as before (the retake check still measures at 0.60 and reports; it did not fire in the last run).
4. **Media search, cause only (no change made).** Both sources fail in the product as configured, so the media agent finds nothing and the page falls back to an SVG diagram with a warning. (a) **Wikimedia answers `403 Please respect our robot policy`** to the product's user agent, `Socra/0.1 (local educational app)` (`graph/media/library.py`): Wikimedia requires a descriptive agent with a contact (a URL or an address). The same query with an agent that has a contact returns 200 and 12 results, all under licences the product allows (CC BY, CC BY-SA, public domain). (b) **Openverse timed out** on every call from the container, at the product's 15 seconds and at 40, for an anonymous request; it is slow or blocking here, and may need registered credentials. So "no picture for Asexual reproduction" is not about the topic or the licence filter: any topic would have none. The fix would be a contact-bearing user agent (taken from the environment, as every setting is), a look at Openverse's anonymous limits, and a live check that `wants_picture` topics get one.

Sixth live run (2 November 2026, same keys, after decisions 1 and 3; 24 minutes, with many `429`s that the retry and fallback absorbed):

| Check | Result |
|---|---|
| Topic judge; calibration pool; quiz of every kind including the retake check; real lesson (concepts, index, revision sheet) | **Pass** |
| Golden topic Binary search, from a quick check to a graded test | **Pass** (the first full pass of any golden topic) |
| `lesson.plan` sets `quantitative` for solving quadratic equations | **Fail**: said false; it had said true in the three earlier runs, so the flag is unreliable for that topic, not wrong every time |
| Golden topic Asexual reproduction | **Fail**: the lesson was built; only the picture is missing (cause above) |
| Golden topic Photosynthesis | **Fail**: the lesson failed its sandbox render check after the repair rounds: `introduction: console.error: Error: <circle> attribute cx: Expected length, "NaN"`, a generated SVG with a `NaN` coordinate |
| Graded attempt on a built lesson | **Fail**: the quick check failed its validator after three attempts (options of two questions not all different), so no lesson was built for it |

For a decision: the quick check still fails now and then even with three attempts, so a check that fails the same way each time could be given the same fix as the others (a repair step that rewrites only the flagged questions rather than the whole bundle); the `NaN` SVG coordinate could be caught by the sandbox's static check before the render; the plan's `quantitative` flag could be derived from the topic judge (`topic.traits`) instead of a second opinion from the planner.

### Phase 10: Credits and payments

Credits for the work that costs model calls, earned by studying, bought through Stripe or Razorpay. The design is [the spec](../architecture/credits-system.md) and [the implementation plan](../archive/credits-implementation-plan.md) (phases 10.0 to 10.9, each shippable, each ending with `make check` and `make e2e` green). **Phase 10 is complete and switched on:** the credit gate and earning are the defaults, new accounts get 30 credits and existing ones were backfilled first. Sign-in methods (Google, Apple, Microsoft, email OTP) are Phase 11, a separate plan; **public launch is blocked on it** (see below).

- [x] 10.0 Apps, environment, the beat service, `Profile.timezone`, `ActivitySink` and its three call sites, the `quiz.retake` hint, `account_ready`, the 402 handler
- [x] 10.1 Ledger: wallet, buckets, transactions, holds, spend order, append-only, audit
- [x] 10.2 Prices, quote, `CreditGate`, `402`, exempt, hold reconciler, wallet and history endpoints
- [x] 10.3 Earning: signup, daily credit, streak, repair, the hourly tick, the backfill command, and account erasure (built but switched on with the gate in 10.9, except the signup grant)
- [x] 10.4 Plans and periods: one-time, weekly drip, queueing, activation
- [x] 10.5 Wallet, history, streak and buy screens, notices, a cost on every button
- [x] 10.6 Payments core: the gateway port and registry, orders, webhooks, reconciliation, clawback, the fake gateway, the buy flow
- [x] 10.7 Stripe adapter (test mode): `StripeGateway` over `httpx` with a pinned API version, signature and event reading, status lookup and refund; start-up safety checks (`payments.E004`, `E005`); the live checks wait on a working test key
- [x] 10.8 Razorpay adapter (test mode): `RazorpayGateway` over `httpx`, signature and event reading (replay stopped by the event id), status lookup and refund with the admin form's idempotency token; `RazorpayCheckout` (on-page window, script loaded on demand, completion only navigates to the return page); the live checks wait on Razorpay test keys
- [x] 10.9 Console (credits and prices, learner wallets, payments and refunds, revenue beside model cost), Terms and Privacy for credits and payments, `retakes_per_day` and `paise_per_credit` retired, the signup backfill, the credit gate and earning switched on by default, the spec moved to `architecture/` and the plan to `archive/`; Razorpay retry on, and the sweep that settles refunds
- [ ] 11 Sign-in and account verification ([the plan](../to_be_developed/signin-implementation-plan.md)): **public launch is blocked on this**, because with credits on every unverified account gets 30 free credits (signup farming, D15)
  - [x] 11.0 Forwarded-header test and fix, `User` verification fields and canonical email, the mailer port and backends (Brevo, console, outbox), `OutboundMail`, `AuthSettings`, the system checks, the daily purge, the `Clock` port; learners see no change
  - [x] 11.1 Email with a code: pending signup and ticket, codes, `register` 202, `verify`, the verify screen, disposable list, backfill skips unverified
  - [x] 11.2 Password reset by code
  - [ ] 11.3 Google: provider port, flow, linking, the last step
  - [ ] 11.4 Console (see, resend, unlock, mark verified, waiting list), abuse board, Turnstile switch
  - [ ] 11.5 Microsoft (optional, after its verified-email rule is written)
  - [ ] Launch checklist (the plan, 12.7): the domain and its DNS, the Brevo key, Google Cloud, `require_reverification`, the proxy, the Privacy Policy

## Across phases

### The final test on its own screen, taken once ✅

- [x] Backend and API: the generated document has the three content pages only; `GET /lessons/{id}/test` serves the test without answers; one submission per lesson (unique constraint, `409 already_submitted`); `regrade` for a failed grading; `GET …/test/submission`; `test_status` and `test_score` on the lesson; `has_embedded_test` on the document for older lessons; quiz review confirmed to carry everything. Frontend types and API client updated.
- [x] Lesson workspace shell: header with breadcrumb and journey stepper, `?tab=` tabs for a ready lesson, the redesigned building screen with "Your starting point", the friendly failed card, `loading.tsx`, `not-found.tsx`, `error.tsx`, and a `Dialog` primitive that replaces `window.confirm`.
- [x] Lesson viewer as a notebook with index flaps; the document's own navigation and the test page of older lessons are hidden by the runtime.
- [x] Flashcard deck for the quick check and the final test (forward only, resumes after a refresh); the Test tab takes the test once.
- [x] Read-only test results and quick check answers views.
- [x] "My lessons" (continue card, filter chips, status pills, delete in a dialog) and "New lesson" redesigned.
- [x] Five-step setup and the single-page profile, with the same tiles.
- [x] Backend: `POST /onboarding/topic-suggestions` (curated catalogue, `onboarding.suggest_topics` as the fallback and for translation); the setup's last step is built against the request and answer shapes of `backend/onboarding` (see [frontend.md](../reference/frontend.md)).

### The public landing page ✅

- [x] `/` for signed-out visitors, built from the mockup's screen 11: hero with a try-it question, "How it works" walkthrough, "Three ways forward" carousel, proof strip, call to action and footer; scroll reveal and reduced-motion handling; `RouteGuard` sends signed-in visitors on; the system-status widget and the Swagger/admin links are gone from public UI.
- [x] Read `socra.pendingTopic` back on the screens after sign-up (it stays until the setup ends, so a refresh on the last step keeps it), and write `/privacy` and `/terms`.
- [x] Hero question bank (`marketing.DemoQuestion`, `GET /api/landing/demo-question`): superseded by the sample Quick check, and removed (see "Follow-up on the landing page" below).
- [x] "How it works": the stage is as tall as the step list, caption top-left, preview under it.
- [x] "Your score decides" carousel (replaced by the rebuilt page; `Autoplay` removed with it).

### Landing page refresh and console testimonials ✅

- [x] The landing page rebuilt from `docs/design/mockups/landing-page-mockup.html`: sample Quick check (client-side, no network), how it works, what learners say, adapts, progress, revise, pricing, FAQ, final band, footer; light and dark; no horizontal scroll from 360px.
- [x] Every number on it from `GET /api/public/pricing` (a console price edit changes the page); `GET /api/public/testimonials` returns only published, consented, non-sample ones; with none, the maker's note.
- [x] `marketing.Testimonial` (published only with consent, never a sample: model validation and a database constraint), the console's **Testimonials** screen (list, add, edit, reorder, publish, delete, all audited), and `manage.py seed_sample_testimonials` (DEBUG only).
- [x] A signed-in visitor can open `/` and sees "Go to my lessons".
- [ ] A photo for the maker's note; the legal and tax review of the prices shown (see Phase 10's open items).

### Follow-up on the landing page ✅

- [x] Removed the dead hero question bank: `marketing.DemoQuestion` (model, admin, picker, serializers, view, `GET /api/landing/demo-question`, the `landing_demo` throttle and its two settings), a migration (`marketing.0004`) that drops the table, the frontend `DemoQuestion` type and the unused `lib/autoplay` and `lib/reveal-policy`, with their tests.
- [x] Solid primary buttons are readable: a new `--primary-action` token family (fill, hover, pressed, edge) gives the label at least 4.5:1 in light and dark; `Button`'s default variant and the study follow-up's chosen chip use it, the general `--primary` teal is unchanged; `lib/primary-button-contrast.test.ts` fails if a pair drops under 4.5:1.
- [x] Every other label on a teal fill (avatar initial, step numbers, badges, streak days, answer-letter chips, choice tiles, the sign-in side panel, the landing page's step chips) uses the same family, with the pairs and a source guard in that test; the unused `lib/walkthrough` and `lib/slide-cycle` are removed.

### Onboarding topic suggestions (backend) ✅

- [x] `GET /api/profile/options` (every choice list with its label); `Profile.preferred_language` has choices and `notes` a 2000-character limit, with a migration that fits existing rows (unknown language becomes English, long notes are cut).
- [x] `POST /api/onboarding/topic-suggestions`: four first topics from a curated catalogue (Classes 6 to 12, five field families at two levels, professional, interview and self-learner lists), with rule-built reasons, paging, and a per-learner throttle ([onboarding.md](../reference/onboarding.md)).
- [x] Node `onboarding.suggest_topics` (optional, seeded for speed): a model for a field the catalogue does not know, and one batched translation for other languages; Redis cache (30 days); any failure gives the English catalogue (`source: fallback`), never a `5xx`.

### The staff console ✅

The backend of an in-app admin ("Socra Console"), replacing the Django admin for the everyday jobs. The design is [design.md §4.16](../architecture/design.md#416-console-the-staff-api) and the endpoints are in [api.md](../reference/api.md#console-staff-only).

- [x] App `console`: staff-only access (404 for anyone else), a `120/min` throttle per staff member, `AuditEntry` and `AuditTrail`, `is_staff` on `/auth/me`.
- [x] `overview`: health with worker count, lessons, spend against `CONSOLE_MONTHLY_BUDGET_USD`, calls, daily spend by provider, funnel, slowest steps and four attention rules.
- [x] `usage` and `usage/export.csv`: KPIs, per model and per step with `percentile_cont`; one definition of ok, retried, failed and fallback (`CallOutcomes`); `ModelCall` indexed on `(model_name, created_at)` and `(node_key, created_at)`; `ModelCall.rate_limit_wait_ms`.
- [x] `runs`: list, detail with a timeline (`GraphRun.node_timings`, written by `GraphRunRecorder`) and the last 20 calls, retry and cancel through the learner's own services.
- [x] `providers` and `models`: list, change, add, delete (409 naming the steps), and a 20-second test that keeps `LLMModel.last_probe_*`.
- [x] `nodes` and `profiles`: grouped routing, atomic validated replace, profile preview; seed profiles `balanced` and `quality` next to `cheap`.
- [x] `flow-settings` with the admin form's validation and the routing thresholds (`RoutingPolicy.thresholds`); read-only `learners`; `audit`.
- [x] `lib/types.ts` and `lib/console-api.ts` (typed client).
- [x] The console UI, built from `docs/design/mockups/socra-admin-mockup.html`, screen by screen: lesson runs, the shell with Overview and Usage & cost, Models, Model routing and Lesson settings, Learners and Change log (see [frontend.md](../reference/frontend.md#console-lesson-runs-consoleruns)).

### Test speed and audit ✅

Branch `chore/test-speed`; the analysis, the measurements and every decision are in [test-audit.md](test-audit.md).

- [x] A fast password hasher under pytest only (with tests that it is never active outside it), `pytest-xdist` (`PYTEST_WORKERS`, `--dist worksteal`), the in-memory `db-test` Postgres, the `migration` marker, `make test-serial`, `make test-for`, `make check-full`: the backend suite went from 16:50 to under 2 minutes.
- [x] e2e: a frontend readiness check, a warm-up of every page, the learner specs in parallel after the shared-state ones, waits for state instead of timers, the specs that only repeated unit tests slimmed: `make e2e` from 10:12 to about 5:30.
- [x] `e2e/spec-map.json`, `make e2e-affected` and the guard test (in `make lint` and CI).
- [x] 17 trivial or placeholder tests, 2 duplicates and 2 removed-name assertions deleted (listed in the audit); the FAQ and progress-example tests assert numbers and structure, not sentences.
- [x] Gap tests G1 to G7, each seen failing with its lock or check removed (G5 found a defect: two staff revising one price at once; fixed with a per-key advisory lock in `PriceCatalog`).
- [ ] Remove the legacy readers' tests (`tests/graph/test_levels.py` legacy cases, `tests/lessons/test_renames.py`) **together with the legacy reader code**, as one task: all stored data is dev data and migrated, so the readers have nothing left to read. They were left alone here on purpose.
- [x] The money gaps from the one-off coverage run are closed (the webhook-replay race, a hostile body, a body over the size limit refused before any database work, an already-fulfilled and a not-paid order, a reserve settled while an account is erased), each test seen failing against a deliberately broken version.
- [ ] Gaps the one-off coverage run (98.9 % of lines) showed that remain: `payments/clawback.py` a refund share that rounds to no credits (36); `credits/erasure.py` a list in the scrubbed data (156); `credits/ledger.py` a hold key reused for something else (143); `accounts/views.py` sign-out with a dead refresh token (164-165); `accounts/throttling.py` a login with no usable email (22); `core/management/commands/sync_to_supabase.py` is not run by any test (0 %): left for the Supabase/RLS task.
- [ ] `sandbox` render checks start a browser per call (about 4 s each, 8 tests) and the unreadable-document test waits through three 10 s page deadlines on purpose. Starting one browser per session would change how untrusted lesson code is isolated, so it was not done; shortening the unreadable-document wait in `sandbox/scripts/render-check.mjs` (a syntax error is the same on every page) would save about 15 s per broken lesson build as well as in the test.
- [ ] The parallel e2e run found, in `next dev` only, that the warm-up quiz starts its walk twice (React strict mode) and an answer sent between the two is ignored; production starts it once. The spec presses Continue again; the component could ignore the first walk.

### Design alignment ✅

- [x] Close the [refactor backlog](../architecture/design.md#refactor-backlog) for phases 0–2: code brought in line with the object design (OOP, SOLID, the named patterns), each item behaviour-neutral with tests green before and after.
- [x] The backlog items for the lesson-flow code (`graph/`, `lessons/`) landed with Phases 3–6 (grading, validators, prompts, Stage A nodes and the flow builder in Phase 3; media in Phase 5; code generation, the build nodes and the document builder in Phase 6).
- [x] Every existing test file has the header from [testing.md](testing.md#31-the-file-header-required) (unit under test, why, use cases), and `tests/` is linted like the backend.

## Later (not now)

- Deployment (hosting, managed Redis, production settings, media on Supabase Storage)
- A circuit breaker per model
- Letting the learner redo the diagnostic after finishing a lesson, to measure progress
