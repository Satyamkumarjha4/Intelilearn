# Test audit and speed-up plan

Status: **stage 1 of 2 (analysis). Nothing in `tests/`, `backend/`, `frontend/` or `e2e/` has been changed**; this file is the only change. It ends with the decisions that are needed before stage 2 (section 8). Measured on 10 November 2026 on this machine (12 cores, 15 GB), against commit `36b3cc8` of `main`.

## 0. Summary

| | Now | After the proposals (measured where marked) |
|---|---|---|
| `make test` (pytest) | **16 min 50 s** | **1 min 48 s** with all three backend speed-ups (measured, section 3) |
| `make lint` | about 75 s | unchanged (it is not the problem) |
| `make check` | about 18 min | about 3 min |
| `make e2e` | 10 min 12 s on a warm stack (about 11 min cold) | about 4 min with parallel specs and fewer fixed waits (parallel part measured, the rest estimated) |
| e2e during work | the whole run, or nothing | `make e2e-affected`: only the specs a change can touch |

Four findings drive everything:

1. **The backend suite is slow because of password hashing, not because of anything in the tests.** Django's default hasher (PBKDF2, 1,000,000 rounds) takes 0.15 s to make a hash and 0.15 s to check one. Every test that uses the `user` fixture pays for one hash, every test that signs in pays for another, and there are thousands. No setting overrides it. With a fast hasher in tests only, the same 6,525 tests take 5 min 27 s instead of 16 min 50 s, and `tests/console` goes from 164 s to 16 s.
2. **Nothing runs in parallel.** pytest is one process on one core (97 % CPU on one of twelve; the database sits at 3 %). Playwright runs one worker. The suite parallelises well: 8 workers on a fast-hasher run took the whole suite to 1 min 48 s.
3. **The e2e specs cannot simply be run in parallel against the current stack.** The frontend there is `next dev`. When one worker is the first to open a route, the dev server compiles it and Fast Refresh reloads the pages other workers are using, which destroys a half-answered quiz and times the test out after 3 minutes. Warming every route first fixes it (second experiment, section 3.4), but dynamic routes (`/lessons/[id]`, `/quizzes/[id]`) still need warming.
4. **A cold e2e stack can come up broken and say nothing.** On my first cold start every page returned 500 (`next/font/google` could not be resolved in the dev server), every spec failed, and a plain container restart did not cure it; only a full `down -v` and `up` did. `make fake-llm` waits for `/api/health` of the backend only, so it reports success. A frontend readiness check is part of the proposal.

The audit itself (section 6) found **fewer deletions than the size of the suite suggests**: the code is tidy. About 19 tests (about 25 test cases) are trivial, duplicated or guard removed code; they are worth deleting for clarity, not for time (about 1 s of the suite once the hasher is fixed). The real value of the audit is the nine **gaps** at the end of section 6, three of them about money.

## 1. What was measured

### 1.1 `make check`, split by step

Each step run in its own `docker compose run` (about 1.5 s of container start-up is in each figure).

| Step | Seconds | Notes |
|---|---|---|
| `ruff check` | 2.5 | |
| `ruff format --check` | 2.4 | |
| OpenAPI `spectacular --validate` | 8.7 | |
| `bun run lint` (eslint) | 22.2 | |
| `next typegen` | 9.2 | |
| `tsc --noEmit` | 18.5 | my split run failed it for lack of the generated types (typegen ran in another container); the real figure is close to this |
| `bun test` | 9.8 | 2,190 tests in 130 files, **0.7 s** of it is tests |
| **lint total** | **about 75** | |
| pytest collection only | 18.6 | `--collect-only`, including container start-up |
| **pytest** | **1,018** (16:50 inside pytest) | 6,525 passed, 5 skipped, 14 deselected |

`--durations` and a per-test XML report show the pytest time is flat, not lumpy: the sum of every test's own time is 997 s of the 1,010 s, so collection and creating the test database cost about 13 s in all (the first test's set-up is 6.1 s). The average test costs 0.15 s. The largest files:

| File | Tests | Seconds |
|---|---|---|
| `lessons/test_views.py` | 182 | 56.7 |
| `graph/test_sandbox.py` (spawns Node and a browser) | 47 | 52.0 |
| `credits/test_quote_equals_gate.py` | 93 | 30.7 |
| `lessons/test_services.py` | 175 | 30.0 |
| `lessons/test_runner.py` | 47 | 26.0 |
| `quizzes/test_views.py` | 73 | 23.9 |
| `lessons/test_attempts.py` | 50 | 22.6 |
| `console/test_runs.py` | 65 | 21.9 |
| `lessons/test_attempt_migrations.py` | 5 | 17.0 |
| everything else | | each under 15 |

The slowest single tests are `graph/test_sandbox.py::test_an_unreadable_document_is_reported_for_the_page_being_checked` (17.6 s, the first browser launch), `lessons/test_attempts.py::TestOnlySealWritesAnAttemptsAnswers::test_no_code_outside_the_attempt_service_updates_the_answers_or_the_questions_of_an_attempt` (13.5 s, a scan of the source), then a tail of Node-sandbox tests at 3 to 5 s and migration tests at 2 to 4 s. The 12 files of migration tests together take about 60 s (6 %).

### 1.2 `make e2e`, split

| Phase | Seconds |
|---|---|
| `make e2e-down` (delete the stack and its database) | 11.6 |
| stack start-up from nothing (build is cached): containers, migrate, registry, staff user | 51 |
| the same on a stack that is already up | 19 |
| 57 specs run, one worker | 593 |
| **`make e2e` total on a warm stack** | **612** (57 passed, 3 skipped) |

The Playwright time by spec file (one worker, the order the files run in):

| Spec | Tests | Seconds | What dominates |
|---|---|---|---|
| `followups` | 3 | 91.5 | three lesson builds, two quick checks |
| `stop-and-retry` | 2 | 85.0 | builds at four stop delays in one test (66 s) |
| `self-rating` | 6 | 82.8 | four builds, two stop-and-retry rounds |
| `credits` | 11 | 76.9 | a build, a streak read, a 27 s too-poor test |
| `quizzes` | 5 | 68.6 | four quizzes |
| `payments` | 5 | 43.8 | one 26.5 s test that builds a lesson |
| `sheets` | 5 | 41.5 | |
| `journey` | 1 | 39.6 | the whole learner path |
| `landing` | 10 | 25.1 | seven tests plus four widths |
| `console-credits` | 5 | 15.1 | |
| `onboarding-refresh` | 1 | 7.6 | |
| `console` | 2 | 5.3 | |
| `timezone` | 1 | 4.4 | |

Where the time goes inside the specs: about 30 lesson or quiz builds at 8 to 15 s each on the fake model, and **fixed waits**. `e2e/support/deck.ts` and `attempt.ts` wait 450 ms before every card (a card "flies out"), and a learner answers about 200 cards in a run; `Api.until` polls once a second; `stop-and-retry` and `self-rating` sleep 0.6, 1.8 and 3.2 s on purpose; the first visit to each route pays the dev server's compile time (the 10 s first test of `credits` is one).

### 1.3 Are pytest and Playwright run in parallel, and why not

- **pytest: no.** `pytest-xdist` is not a dependency (`backend/pyproject.toml` has only pytest, pytest-django and ruff), so `make test` and the CI `test` job run one process. It is CPU-bound in Python (one core at 97 %, Postgres idle), so it is the case where parallelism helps most. Blockers found: one test builds its parameter id from `uuid.uuid4()` at import time (`tests/payments/test_orders_api.py:45`), so each worker collects different test ids and xdist refuses to start; fixing it is one line (a fixed uuid). Nothing else stopped a run: each worker gets its own test database, the cache is in memory in tests, and the tests that use real threads work under it.
- **Playwright: no, by choice, and the choice is right for the current stack.** `playwright.config.ts` says `workers: 1` because the tests "share one database and one fake model". They do share global state (the price table, the testimonial list, the credit settings), but most do not depend on it. What really stops parallel runs is the dev-server reload described in finding 3.

## 2. Why the hasher is the cause (evidence)

| Run (all 6,525 tests, same machine) | Time |
|---|---|
| now: serial, default hasher | 16:50 |
| serial, `MD5PasswordHasher` | 5:27 |
| `tests/console` alone, default hasher | 2:44 (163.6 s) |
| `tests/console` alone, `MD5PasswordHasher` | 0:16 (16.1 s) |
| `make_password` / `check_password` as measured in the container | 0.150 s / 0.159 s |

`MD5PasswordHasher` in tests is Django's own recommended practice. The fix is a setting that applies only while testing (`TESTING` already exists in `config/settings.py`). All 6,525 tests passed with it, so no test depends on the hash algorithm.

## 3. Speed-ups, ranked by minutes saved

The experiments were run in throwaway containers (`pytest-xdist` installed inside the container for the run, a scratch settings module, a scratch Postgres on tmpfs); no file of the repository was touched. Commands are in the appendix (section 9).

### 3.1 Backend

| # | Change | Backend suite | Saves | Cost and risk |
|---|---|---|---|---|
| B1 | A fast password hasher while testing (`PASSWORD_HASHERS = [MD5PasswordHasher]` when `TESTING`) | 16:50 → 5:27 | **11.4 min** | Three lines in `settings.py`. Tests that check a hash's format would notice; none does. Never active outside tests. |
| B2 | `pytest-xdist`, `-n 8 --dist worksteal` (8, not 12: 12 workers were slower, 2:36 against 2:15, because the sandbox tests also start browsers) | 5:27 → 3:28 with the shared dev database, 2:15 with a test-only database, 1:48 with `worksteal` | **another 2 to 3.5 min** | `uv add --dev pytest-xdist`; fix the `uuid4()` parameter id; `addopts` gets `-n`. Needs a `make test-serial` for debugging. The suite's real-thread tests passed under it. |
| B3 | A test-only Postgres service on tmpfs with `fsync=off` (a `db-test` compose service, used by `make test` and CI through `POSTGRES_HOST`) | 3:28 → 2:15 (8 workers) | **about 1.2 min** on top of B2 | One compose service and one env value. The dev `db` is not touched. The large share is the `TRUNCATE` that every `transaction=True` test pays on teardown, which was 15 to 29 s in a single teardown with 8 workers on the dev database. Skippable if you prefer fewer moving parts. |
| | **B1 + B2 + B3 together** | **16:50 → 1:48** (8 workers, tmpfs Postgres, worksteal) | **15 min** | |

The runs, all 6,525 passed in every one: serial default hasher 16:50; serial fast hasher 5:27; 8 workers fast hasher on the dev database 3:28; 8 workers, tmpfs database, default hasher 4:30 (so the hasher alone still matters under parallelism); 8 workers, tmpfs database, fast hasher 2:15; the same with `--dist worksteal` 1:48; 6 workers 2:28; 12 workers 2:36.

CI (`.github/workflows/ci.yml`, job `test`) runs the same single-process pytest and gets all of B1 and B2 (a GitHub runner has 4 cores, so expect 3 to 4 minutes, not measured). It would use `-n auto`.

Smaller backend items (worth doing once the above is in; each saves seconds):

| # | Change | Saves |
|---|---|---|
| B4 | Mark the 12 files of one-time migration tests `@pytest.mark.migration` and run them in CI and in `make check-full` but not in the default local run (section 6, D) | about 40 s serial, about 6 s at 8 workers |
| B5 | `test_no_code_outside_the_attempt_service_updates_the_answers...` (13.5 s): read each source file once and cache it across the scan | about 10 s serial |
| B6 | `test_remembered_answers_expire_after_the_configured_time` sleeps 1.2 s for real: move the cache's clock instead | 1.2 s and one timing-dependent test fewer |
| B7 | `graph/test_sandbox.py` (52 s, 47 tests): start the sandbox browser once per session | about 20 s serial, unmeasured |

### 3.2 Frontend and lint

Nothing to gain: `bun test` is 0.7 s, eslint 22 s, `tsc` about 20 s, in all 75 s. The only saving is running the four frontend commands in one container and the ruff commands beside them (`make -j`), about 20 s, and I do not recommend it for the added complexity.

### 3.3 e2e, in the order they pay back

| # | Change | Saves | Evidence |
|---|---|---|---|
| E1 | **Run the learner specs in parallel** (a `learner` Playwright project with 4 workers) after a serial `global` project for the specs that change shared state (`landing`, `console-credits`, `credits`, `console`) | about 5 min of the 10 | partly measured, see 3.4 |
| E2 | Replace the 450 ms card waits with a wait for the next card to be ready (and run the browser with reduced motion, which the app already respects, so there is no fly-out to wait for); poll `Api.until` every 250 ms rather than 1 s | up to 90 s | not measured: about 200 cards × 0.45 s; to be measured in stage 2 |
| E3 | A frontend readiness check in `make fake-llm` (the page must answer 200, not only `/api/health`), and a warm-up visit of every route, dynamic ones included | removes the silent cold-start failure and the first-visit compile cost (10 s in `credits`, the 30 s the warm-up took) | measured: the cold failure, and the 30 s warm-up |
| E4 | `make e2e-affected` (section 4) | most of a run on most changes | design |
| E5 | Reuse the running stack between runs: skip `up --build` and the seeding when the stack answers; rebuild only when a trigger file changed | 19 s of 51 s, and the 12 s teardown | measured |
| E6 | Slim the specs that only repeat unit tests, and shorten `stop-and-retry` from four stop delays to two (0 and 1.8 s) and `self-rating`'s retry test to one | about 60 to 80 s | section 6, C |

Rejected: **a production build for the e2e stack** (`next build && next start`) would remove the compile and reload problem for good and make pages faster. I tried it in a throwaway container: the build compiled and type-checked and then crashed with `SIGILL` (illegal instruction) under Bun in the image. It may be a CPU-feature issue of this machine. Worth a stage-2 look if you want it; not assumed.

### 3.4 The two parallel e2e experiments

Both ran the nine learner specs (`followups journey onboarding-refresh payments quizzes self-rating sheets stop-and-retry timezone`, 29 tests, 467 s serial) with `--workers=4` on the running stack:

1. On the stack as it is: **25 passed, 4 failed** in 6 min 25 s. The failures are `locator.click` timeouts after 3 minutes; the browser logs show `[HMR] connected` and `[Fast Refresh] rebuilding` while the deck was on screen, so the page was reloaded under the test.
2. After one warm-up visit of the 26 static routes (30 s, as a throwaway spec): **27 passed, 2 failed** in 4 min 13 s, and both failures are again a 3-minute timeout, on the first test of a worker that opens `/lessons/[id]` or `/quizzes/[id]` for the first time. The 4 min 13 s is those two timeouts, so I did not observe the true parallel time. From the measured serial times (467 s of work over 4 workers, the longest spec 92 s) I expect 2 to 2.5 minutes once the two dynamic routes are warmed too: about 5 minutes saved. That is the case for E3 first, E1 second. This estimate is the weakest number in this document; stage 2 measures it.

## 4. Selective e2e

### 4.1 The map: `e2e/spec-map.json`

A checked-in JSON file with four parts, read by one small class (`SpecSelector`, `e2e/spec-selector.ts`, unit-tested with `bun test`):

- `groups`: names for sets of specs (`@build` = the six specs that run a lesson or quiz graph; `@money`; `@console`).
- `triggers`: globs whose change means **run everything**, each with the reason.
- `map`: globs → specs (the specs may be a `@group`). A file may match several entries: the specs are added together.
- `no_spec`: globs that need no browser run, each with the reason.
- `manual`: specs never run automatically (the two live-provider ones, `payments-stripe` and `payments-razorpay`, which `make e2e` skips today).

Order of decision for each changed file: trigger → full run; else `no_spec` → ignored; else map → those specs; **else unmapped → full run** (and the file is named in the output). I checked the draft below against the 1,376 tracked files: 171 trigger, 469 need no spec, 736 map, **0 unmapped**, no spec unreachable (except the two manual ones).

### 4.2 The "always run everything" triggers, and why

| Trigger (glob) | Why a change there cannot be narrowed |
|---|---|
| `frontend/proxy.ts`, `lib/route-guard.ts`, `lib/setup-marker.ts`, `lib/safe-redirect.ts`, `lib/session-probe.ts`, `lib/auth-form.ts`, `app/auth/**`, `components/auth-provider.tsx` | Sign-in, the session cookie and the route guard are in front of every spec. |
| `frontend/app/layout.tsx`, `error.tsx`, `global-error.tsx`, `loading.tsx`, `not-found.tsx`, `components/site-header.tsx`, `status-card.tsx`, `components/ui/**`, `lib/utils.ts`, `lib/initials.ts` | The shell and the shared primitives every page is drawn with; a break there breaks selectors everywhere. |
| `frontend/app/api/**`, `lib/api.ts`, `next.config.ts` | The API client and the `/api` proxy carry every call (cookies, CSRF, the raw webhook body). The proxy is exactly what only e2e proves. |
| `frontend/package.json`, `bun.lock`, `Dockerfile`, `tsconfig.json`, `.dockerignore`, `backend/pyproject.toml`, `uv.lock`, `Dockerfile`, `.dockerignore`, `.python-version`, `sandbox/package.json` | Dependencies and images change what runs in the stack. |
| `docker-compose.yml`, `docker-compose.e2e.yml`, `.env.example`, `Makefile`, `e2e/**`, `tests/e2e/**` | The stack, its environment, the fake model and canned lesson, and the e2e harness (support files, fixtures, config). |
| `backend/config/**`, `core/**`, `accounts/**`, `manage.py` | Settings, URLs, auth, throttles, the error format, start-up: shared by every request. |
| migrations of `accounts`, `lessons`, `quizzes`, `credits`, `payments`, `llm_registry`, `console` | The tables every flow touches (user, lesson, run, ledger, order, registry, audit); the stack applies them for real on first start, and a bad one fails everything. Migrations of `marketing` (one table, the landing page's) only map to `landing`. |

Deliberately **not** triggers: `backend/graph/**`, `lessons/**`, `quizzes/**`, `llm_registry/**` (they map to the six build specs, which is what they can break), `backend/credits/**` and `payments/**` (they map to the money specs, `landing` and `journey`), `console/**`, `marketing/**`, `onboarding/**`, and everything under `frontend/components` and `lib` except the files named above.

### 4.3 The full initial map (draft; `e2e/spec-map.json`)

```json
{
  "groups": {
    "build":   ["journey.spec.ts", "followups.spec.ts", "quizzes.spec.ts", "self-rating.spec.ts", "sheets.spec.ts", "stop-and-retry.spec.ts"],
    "money":   ["credits.spec.ts", "console-credits.spec.ts", "payments.spec.ts"],
    "console": ["console.spec.ts", "console-credits.spec.ts", "landing.spec.ts"]
  },
  "manual": ["payments-stripe.spec.ts", "payments-razorpay.spec.ts"],
  "triggers": [
    {"globs": ["frontend/proxy.ts", "frontend/lib/route-guard.ts", "frontend/lib/setup-marker.ts", "frontend/lib/safe-redirect.ts", "frontend/lib/session-probe.ts", "frontend/lib/auth-form.ts", "frontend/app/auth/**", "frontend/components/auth-provider.tsx"],
     "why": "sign-in, the session cookie and the route guard sit in front of every spec"},
    {"globs": ["frontend/app/layout.tsx", "frontend/app/error.tsx", "frontend/app/global-error.tsx", "frontend/app/loading.tsx", "frontend/app/not-found.tsx", "frontend/components/site-header.tsx", "frontend/components/status-card.tsx", "frontend/components/ui/**", "frontend/lib/utils.ts", "frontend/lib/initials.ts"],
     "why": "the shell and primitives every page is drawn with"},
    {"globs": ["frontend/app/api/**", "frontend/lib/api.ts", "frontend/next.config.ts"],
     "why": "the API client and the /api proxy (cookies, CSRF, raw webhook bodies) carry every call"},
    {"globs": ["frontend/package.json", "frontend/bun.lock", "frontend/Dockerfile", "frontend/tsconfig.json", "frontend/postcss.config.mjs", "frontend/.dockerignore", "backend/pyproject.toml", "backend/uv.lock", "backend/Dockerfile", "backend/.dockerignore", "backend/.python-version", "sandbox/package.json"],
     "why": "dependencies and images change what runs in the stack"},
    {"globs": ["docker-compose.yml", "docker-compose.e2e.yml", ".env.example", "Makefile", "e2e/**", "tests/e2e/**"],
     "why": "the stack, its environment, the fake model and the e2e harness"},
    {"globs": ["backend/config/**", "backend/core/**", "backend/accounts/**", "backend/manage.py"],
     "why": "settings, URLs, auth, throttles, error format, start-up"},
    {"globs": ["backend/accounts/migrations/**", "backend/lessons/migrations/**", "backend/quizzes/migrations/**", "backend/credits/migrations/**", "backend/payments/migrations/**", "backend/llm_registry/migrations/**", "backend/console/migrations/**"],
     "why": "migrations of the shared tables (user, lesson, run, ledger, order, registry, audit)"}
  ],
  "map": [
    {"globs": ["frontend/app/page.tsx", "frontend/app/landing.css", "frontend/app/globals.css", "frontend/components/landing/**", "frontend/lib/landing/**", "frontend/lib/landing-content.ts", "frontend/components/brand/**", "frontend/components/theme-toggle.tsx", "backend/marketing/**"],
     "specs": ["landing.spec.ts", "journey.spec.ts"]},
    {"globs": ["frontend/app/onboarding/**", "frontend/components/onboarding/**", "frontend/components/profile/**", "frontend/components/use-profile*.ts", "frontend/lib/onboarding-flow.ts", "frontend/lib/topic-suggestions.ts", "frontend/lib/pending-topic.ts", "frontend/lib/starting-point.ts", "frontend/lib/browser-timezone.ts", "backend/onboarding/**"],
     "specs": ["journey.spec.ts", "onboarding-refresh.spec.ts", "timezone.spec.ts"]},
    {"globs": ["frontend/app/profile/**"], "specs": ["timezone.spec.ts"]},
    {"globs": ["frontend/app/lessons/**", "frontend/components/lessons/**", "frontend/components/markdown.tsx", "frontend/components/confirm-dialog.tsx", "frontend/components/form-field.tsx",
               "frontend/lib/lesson*.ts", "frontend/lib/{journey,pipeline,stage-view,new-lesson,mastery-options,level-choice,study-sheets,star-scale,stop-control,practice-session,sandbox-bridge,code-languages,cheat-groups,plain-notes,plain-text,unsaved-guard,clipboard,answers-view,page-links,question-*,attempt-*,deck-*,test-*,calibration-walk,followup-*,run-events,run-follower,chips,format}.ts",
               "frontend/lib/pdf/**", "backend/lessons/**", "backend/graph/**", "backend/llm_registry/**", "sandbox/**"],
     "specs": ["@build", "credits.spec.ts"]},
    {"globs": ["frontend/app/quizzes/**", "frontend/components/quizzes/**", "frontend/lib/quiz*.ts", "backend/quizzes/**"],
     "specs": ["quizzes.spec.ts", "journey.spec.ts", "followups.spec.ts"]},
    {"globs": ["frontend/app/console/**", "frontend/components/console/**", "frontend/lib/console-*.ts", "frontend/lib/console-testimonials/**", "frontend/lib/{model-*,routing-*,flow-*,run-filters,run-timeline,run-actions,run-text,table-sort,probe-queue,chart-shapes}.ts", "backend/console/**"],
     "specs": ["@console"]},
    {"globs": ["frontend/app/{buy,wallet,streak}/**", "frontend/components/credits/**", "frontend/components/payments/**", "frontend/lib/credits/**", "frontend/lib/payments/**", "frontend/lib/action-refused.ts", "frontend/lib/console-credits/**", "backend/credits/**", "backend/payments/**"],
     "specs": ["@money", "landing.spec.ts", "journey.spec.ts"]}
  ],
  "no_spec": [
    {"globs": ["docs/**", "**/*.md", "tests/**/*.py", "frontend/**/*.test.ts", "frontend/lib/types.ts", "frontend/lib/contrast.ts", "frontend/lib/mailto.ts"],
     "why": "docs, unit tests, and files that only type-check or are pure helpers with no screen of their own"},
    {"globs": ["frontend/app/{privacy,terms,contact}/**", "frontend/components/legal/**", "frontend/components/contact/**", "frontend/lib/legal-*.ts", "frontend/content/**"],
     "why": "static legal and contact pages: no browser flow, covered by the legal-document unit tests"},
    {"globs": ["frontend/app/icon.svg", "frontend/app/apple-icon.png", "frontend/components.json", "frontend/eslint.config.mjs", "frontend/.gitignore", ".github/**", ".gitignore"],
     "why": "icons, lint and repository plumbing: nothing a browser flow reads"}
  ]
}
```

Known limits of a folder map, said plainly: it follows areas, not imports. A change to `frontend/lib/format.ts` is mapped to the lesson specs although a console page also uses it. The unit tests cover pure `lib` code; the **full `make e2e` before a merge to main is the backstop** (section 7), and a file that nobody mapped runs everything rather than nothing.

### 4.4 `make e2e-affected`

```
make e2e-affected                 # against main
make e2e-affected BASE=feature/x  # against another ref
```

1. The changed files are the union of `git diff --name-only $(git merge-base BASE HEAD)` (commits plus staged and unstaged changes) and the untracked files. If the base cannot be resolved, it says so and runs everything.
2. `bun e2e/affected.ts` (a thin script around `SpecSelector`) prints a table, then the verdict:

   ```
   changed file                              why                         specs
   backend/credits/ledger.py                 map: credits area           credits, console-credits, payments, landing, journey
   frontend/components/lessons/deck.tsx      map: lessons area           journey, followups, quizzes, self-rating, sheets, stop-and-retry, credits
   docs/process/testing.md                   no_spec: docs               -
   running 7 of 13 specs
   ```

   A trigger prints `FULL RUN because backend/accounts/views.py matches "settings, URLs, auth..."` and an unmapped file `FULL RUN because X is in no map entry (add it to e2e/spec-map.json)`. Nothing to run says so and exits 0.
3. It reuses the running throwaway stack if the API and the frontend page both answer and the stack is not older than the newest trigger file; otherwise it runs `make fake-llm`.
4. It runs the chosen specs, with the same environment as `make e2e`.

### 4.5 The guard test: `e2e/spec-map.test.ts`

Plain `bun test` in `e2e/` (no browser, no stack), run by `make lint` and by the CI `lint` job (which already has Bun; one more line in each). It fails when:

- a `tests/*.spec.ts` is selected by no map entry and not listed in `manual`;
- a map entry names a spec that does not exist, or a glob matches no tracked file (a dead glob);
- any **source folder** (`backend/<app>`, `frontend/app/<route>`, `frontend/components/<group>`, `frontend/lib/<group>`, `sandbox`) has no file covered by a trigger or a map entry and is not wholly in `no_spec`, and any **file** is classified nowhere (the draft above leaves none);
- the `no_spec` list grows without a `why`, or a trigger without one.

The allow-list is the `no_spec` block: the legal and contact pages, the icons and tooling files, docs and unit tests. That is the explicit, short list of what genuinely needs no spec.

## 5. Where the e2e specs overlap the fast tests

Detail for the table in section 6, C. The specs that remain after slimming each prove something only a browser or the real stack can: the proxy, cookies and CSRF, the card deck, SSE and polling, a build that really runs on the worker, widths, keyboard use. The checks listed for slimming are API-only (no browser needed) and have a named unit test.

## 6. The audit

### How it was done, and its limits

All 263 backend test files (4,047 test functions, 6,525 test cases), the 130 frontend test files, the 15 e2e specs and `tests/support` were scanned by script for: identical or near-identical bodies (AST hash with decorators and arguments, and a token-overlap measure within each file), identical names across files, tests with one or two statements, tests with no assertion, `hasattr` and `not in` checks of removed names, assertions of constants and defaults, real sleeping and wall-clock use, and routes or public methods that no test names. Every candidate below was then read. I **did not read each of the 6,500 test bodies line by line**: a test that is long, behavioural and unique would not have been found by these scans, and the "gaps" below come from the rules in the testing contract and from reading the money, auth and publishing tests in full, not from a coverage tool. **Nothing was run with coverage** (it is not in the dependencies); if you want a line-coverage figure to back the gap list, it can be added in stage 2 as a one-off.

Result in one line: the suite is tidy. Exact duplicates are rare, most "same name in two files" pairs are the Stripe and Razorpay tests mirroring each other on purpose, and almost everything small is a parametrised rule. Hard rule applied: **nothing is proposed for deletion that protects money, payments, auth, the ledger or security unless another test, named, covers the same thing.**

### A. Trivial, placeholder or guarding code that is gone (propose to delete)

| File::test | Why |
|---|---|
| `tests/config/test_credits_settings.py::test_the_payments_app_is_installed_and_holds_its_three_models` | Phase-10.0 placeholder ("the apps are empty"). Lists a model's names; fails when a model is added, proves nothing a model test does not. |
| `…::test_the_credits_app_is_installed` | If the app were missing, every credits test would fail first. |
| `…::test_the_action_gate_is_still_the_open_one_and_the_activity_sink_does_nothing` | Not a product rule: it asserts the autouse test pin, and its name is now wrong (the default has been the credit gate since 10.9). Its body is identical to `tests/credits/test_switch_on.py::TestTheDefaults::test_an_ordinary_test_still_runs_on_the_open_gate_and_the_do_nothing_sink`, which stays. |
| `…::TestPaymentSettings::test_each_provider_key_exists_as_text` (5 cases) | A setting that is a string is a string. A missing key is caught by `payments.E004`/`E005` (`tests/payments/test_safety_checks.py`). |
| `…::TestPaymentSettings::test_gateways_enabled_is_a_list_of_names`, `test_the_default_gateway_is_stripe_unless_the_environment_says_otherwise` | Assert types and "not empty"; behaviour is covered by `tests/payments/test_gateway_port.py` (the registry) and `test_safety_checks.py`. |
| `…::TestPaymentSettings::test_the_dollar_rupee_rate_is_a_positive_number` | An environment default; its use is covered by `tests/console/test_revenue.py` (rupees at the rate shown, exact to the paisa). |
| `tests/graph/nodes/test_mastery.py::test_the_single_sheet_nodes_of_the_old_choice_are_gone` (3 cases) | `not hasattr`: guards code that no longer exists. |
| `tests/graph/test_codegen.py::test_the_document_has_no_test_page` | Asserts a constant and the absence of a method. |
| `tests/payments/test_razorpay_gateway.py::TestTheGateway::test_the_api_has_no_version_to_pin` | `not hasattr(RazorpayApi, "API_VERSION")`: absence of a name. |
| `tests/graph/test_quiz_config.py::TestPresets::test_short_and_long_answers_start_at_ten` | Asserts a constant; the rule itself (a five-question quiz cannot pick short answers) is tested by the refusal tests in the same file and `tests/quizzes/test_views.py`. |
| `tests/quizzes/test_topic_traits.py::TestTheGatewayJudge::test_the_default_gateway_waits_at_most_a_second_for_a_rate_limit` | Asserts a class constant. |
| `tests/onboarding/test_cache.py::test_the_ttl_is_thirty_days_unless_configured` | Asserts a default; the TTL being used is tested in the same file (`{77}` timeouts test). |
| `tests/graph/questions/test_dedupe.py::TestStemHash::test_it_is_64_hex_characters` | SHA-256 is 64 hex characters. |
| `tests/graph/schemas/test_study.py::test_an_unknown_kind_has_no_schema` | `"wallpaper" not in MATERIAL_SCHEMAS`: dict membership. |
| `tests/graph/test_levels.py::TestLevel::test_parses_an_existing_level`, `TestDifficulty::test_parses_an_existing_difficulty` | Identity (`parse(x) is x`); the parsing is covered by the neighbouring table-driven tests. |

Also, lines to drop from tests that stay (not whole tests): `assert not hasattr(settings, "retakes_per_day")` in `tests/lessons/test_attempt_models.py::TestFlowSettingsAdditions::test_the_new_settings_have_the_documented_defaults`, and `assert not hasattr(first, "paise_per_credit")` in `tests/credits/test_models.py` (both assert a removed name).

### B. Duplicates

| File::test | Duplicate of | Action |
|---|---|---|
| `tests/graph/test_quiz_assessment.py::TestRegistry::test_the_keys_are_listed` | `tests/graph/test_assessment.py::TestRegistry::test_the_keys_are_listed` (the same `AssessmentSources.keys()` assertion, the same six keys) | delete one |
| `tests/lessons/test_services.py::TestCreateSheets::test_a_refused_ask_creates_nothing` | `…::TestCreateSelfRated::test_a_refused_ask_creates_nothing` (identical body, the same `create` with a refusing gate) | delete one; the gate refusal is also covered by `tests/lessons/test_action_gate.py` and `tests/credits/test_gate_call_sites.py` |
| `tests/config/test_credits_settings.py::…gate_is_still_the_open_one…` | `tests/credits/test_switch_on.py::…open_gate_and_the_do_nothing_sink` | already in A |

Overlap that I looked at and **recommend keeping**, because it protects money or is a different layer: the Stripe and Razorpay mirrors (`test_*_events`, `test_*_gateway`, `test_*_flow`: same shapes, different providers, so a regression in one adapter shows in one place); the refund and dispute cases that appear in `test_order_events.py` and again in `test_stripe_flow.py` and `test_razorpay_flow.py` (the first proves the provider-neutral state machine, the others that each adapter feeds it); the gate tested in `test_credit_gate.py`, `test_gate_call_sites.py` and `lessons/test_action_gate.py` (unit, the eight call sites, the services); the testimonial publish rule at three layers (`test_testimonial_model.py`, `console/test_testimonials.py`, `marketing/test_public_testimonials.py`), where each layer refuses it its own way and the last never returns an unconsented row even without the database constraint.

### C. e2e checks that only repeat what a fast test proves (candidates to slim)

Every one is API-only (no browser step) and names its covering test. Time saved is small per test (1 to 3 s); the point is a shorter, clearer spec set.

| Spec::test | Covered by | Proposal |
|---|---|---|
| `credits.spec.ts::a new learner has the 30 signup credits, and the wallet, the quote and the history answer for them` | `tests/credits/test_views.py`, `test_signup_grant.py` | merge these four API reads into one "the credits API answers through the proxy" test |
| `credits.spec.ts::the plans on offer carry the spec's prices in paise…` | `tests/credits/test_plans_view.py` | (same merge) |
| `credits.spec.ts::a new learner has no streak, nothing to repair…` | `tests/credits/test_streak*.py`, `test_views.py` | (same merge) |
| `credits.spec.ts::the quote refuses what is not a real question, and nobody signed out can ask` | `tests/credits/test_views.py` (quote validation and 401) | (same merge) |
| `self-rating.spec.ts::what the API refuses when a lesson is asked for` | `tests/lessons/test_views.py`, `test_services.py` | delete |
| `console-credits.spec.ts::a learner meets the page that does not exist, and the endpoints answer 404` | `console.spec.ts` (the same for `/console`), `tests/console/test_credits_access.py`, `test_access.py` | delete |
| `payments.spec.ts::a refund takes back only what is unspent` | `tests/payments/test_order_events.py`, `tests/console/test_payments_board.py` | delete |
| `payments.spec.ts::the return page alone, a wrong signature and a wrong amount grant nothing` | `tests/payments/test_webhook_view.py` (a bad signature, no query), `test_order_events.py` (amount mismatch) | keep only the "return page alone grants nothing" step (that one is the browser's seam) |
| `quizzes.spec.ts::a five-question quiz cannot ask for short or written answers; ten can` | `frontend/lib/quiz-config-form.test.ts`, `tests/graph/test_quiz_config.py`, `tests/quizzes/test_views.py` | keep the "choice is not on screen" half, drop the by-hand API half |
| `self-rating.spec.ts::a self-rated build that is stopped is picked up by Retry…` and `stop-and-retry.spec.ts::…wherever the stop landed` | the same Retry path; `tests/lessons/test_runner.py`, `test_retry_stage.py` cover the logic, the original bug was a timing race only the stack shows | keep two stop points (0 ms and 1.8 s) in `stop-and-retry`, one in `self-rating` |
| `landing.spec.ts` four-width test | one browser per width | one test that resizes the same page through the four widths (saves three browser starts) |

Not proposed for slimming: `journey`, `followups` (the policy is unit-tested, but the pop-up on the result is the browser's), `sheets`, `onboarding-refresh`, `timezone` (the browser's zone), `payments` one-time and plan (the signed callback through the proxy), `credits` too-poor and notices, the console price/wallet/erase flows (money, audited writes).

Also flagged: **specs that never run in `make e2e`**: `payments-stripe.spec.ts` (1 test) and `payments-razorpay.spec.ts` (2 tests) skip without keys, and the Razorpay spec's own header says it "has not yet been run against a live test account"; the three tests are unverified.

### D. One-time migration tests (keep, but not on every run)

12 files, about 60 s of the suite: `lessons/test_migrations.py`, `test_attempt_migrations.py`, `test_first_set_migration.py`, `test_retire_three_sheets_migration.py`, `test_lesson_entry_columns.py::TestMigrations`, `test_followup_columns.py::TestMigration`, `quizzes/test_migrations.py`, `accounts/test_migrations.py`, `test_deleted_at_migration.py`, `test_timezone_migration.py`, `credits/test_migrations.py`, `credits/test_plan_models.py::TestTheMigrations`. Each runs a data migration forward and backward on a real database. After a migration has been applied everywhere, such a test only guards a rollback and a backfill that will not run again. **Do not delete**: `credits/test_migrations.py` (the ledger's append-only trigger) and `credits/test_plan_models.py::TestTheMigrations` (the plan rows) protect money and stay in every run. For the rest, propose a `migration` marker so they run in CI and in `make check-full`, not in the everyday local run (B4). Related, kept until you say all stored data is migrated: the legacy readers' tests (`graph/test_levels.py` legacy cases and `lessons/test_renames.py`, which are not migration tests and run fast).

### E. Flaky or timing-dependent

| Where | What | Fix |
|---|---|---|
| `tests/lessons/test_idempotency.py::TestCacheIdempotencyStore::test_remembered_answers_expire_after_the_configured_time` | sleeps 1.2 s of real time against a 1 s cache expiry | move the cache's clock (B6) |
| `e2e/support/deck.ts`, `attempt.ts` | fixed 450 ms before each card | wait for the next card (E2) |
| `stop-and-retry.spec.ts`, `self-rating.spec.ts` | fixed stop delays of 0, 0.6, 1.8, 3.2 s; the build's speed decides where the stop lands | keep two, accept either outcome, as the test already does |
| `quizzes.spec.ts:33` | `waitForTimeout(1000)` | wait for the state it is waiting for |
| `landing.spec.ts::the maker's note shows until a testimonial is published…` | assumes the testimonial list is empty at the start | clear published testimonials first (needed to reuse a stack between runs, E5) |
| `landing.spec.ts`, `console-credits.spec.ts` | change a price and put it back at the end; a crash in between leaves the price changed for every later spec | restore in a `finally` / `afterEach` |
| `e2e` overall | the whole thing depends on the dev server's compile order | warm-up and a readiness check (E3) |
| 92 uses of the wall clock in backend tests (`datetime.now()`, `timezone.now()`) | mostly a "now" for a row, not an assertion on it; the credits code has `FakeClock`. Three in `tests/accounts/test_views_timezone.py` compare near a 30-day boundary | no action; watch |

### F. Gaps: important rules with no test

Ranked by the damage if the rule broke. Section 8 lets you choose which to write. (Everything else in credits, ledger, gate, payments, webhooks, auth and testimonials was read and is well covered: the ledger has real-thread, random-walk and invariant tests; webhooks have bad signature with no query, replay, unknown gateway, 413; the testimonial rule is tested at the model, the database, the console and the public endpoint.)

| # | Gap | Why it matters | Proposed test |
|---|---|---|---|
| G1 | **Two administrators refund the same order at once, each with their own token, and together refund more than was paid.** `payments/refunds.py` locks the order (`select_for_update`, lines 128 and 174) but only the same-token race is tested (`test_admin_refund_token.py::test_two_threads_with_one_token_ask_once`); different tokens are tested only one after another. | money | `django_db(transaction=True)` with a barrier and two threads: the total refunded never exceeds the amount; remove the lock once to see it fail |
| G2 | **Two hourly ticks at once start the same plan period twice**, granting a week's credits twice (`credits/plans/activator.py:52` locks; `test_plan_tick.py` has no concurrent case, and `PeriodActivator.start_due` is not named by any test). | money | two threads on `PeriodActivator`, one grant |
| G3 | **No test that every API route needs a sign-in unless it is on a short allow-list.** Each app has its own ("every endpoint requires a signed-in user" in `lessons/test_views.py`, the console guard in `test_audit.py`) but nothing walks `get_resolver()` for the whole API. A new view that forgets `IsAuthenticated` ships open. The `AllowAny` views today are health, CSRF, register, login, refresh and logout, the profile options, the signed media URL, the payment webhook and the two public landing endpoints. | security | walk every URL, call it anonymous, expect 401/403/404 except the named allow-list, which must itself be checked against `AllowAny` |
| G4 | **Registering is rate-limited (`AuthRateThrottle` on the register view) but only login and refresh are tested** (`accounts/test_throttling.py`). | security, abuse | one test beside the login ones |
| G5 | **A staff member editing a price while another does** (`credits/pricing/book.py:62,76` lock and keep one live row per key) has no concurrency test. | money-adjacent | two threads revising one key: one live row, history kept |
| G6 | **Inactive account sign-in**: only refresh is tested for a deactivated user (`test_refresh_fails_for_deactivated_user`); sign-in is covered only through the erasure test. | auth | one test: `is_active=False` cannot log in, with the same error as a wrong password |
| G7 | `PurchaseDesk.terms_of`, `PeriodActivator.start_due` and `StreakMilestones.next_after` are named by no test (they are covered only through callers). | small | direct tests, a few lines each |
| G8 | **A cold e2e stack with a broken frontend passes `make fake-llm`.** | wasted time and a misleading result | the readiness check in E3 |
| G9 | **`xdist` cannot start** because of one `uuid4()` in a parameter id. | blocks B2 | the one-line fix |

Frontend: the 2,190 unit tests are fine and cost 0.7 s. A few pin copy (`faq-content.test.ts::there are eight, in order` and exact answer strings, `progress-example.test.ts::the label names each attempt and its score`): they break when the words are improved, and protect nothing but the words. Not proposed for deletion; I would rewrite them to assert the numbers and not the sentences, if you want them touched.

### Time saved by the deletions

About 19 tests in A and B (about 25 test cases). At the average of 0.15 s a test today that is about 7 s of 1,010; after B1 it is about 1 s. **The deletions are about clarity, not speed**; the speed is B1 to B3 and E1 to E3. Section D's marker saves about 40 s serially and is worth more than all of A to C together.

## 7. Proposed working rules

For `docs/process/testing.md` (a new section 6.2, replacing the sentence that `make check` is "before you call the work done" for every task) and `CLAUDE.md`'s Tests and Git sections:

| When | Run | Never |
|---|---|---|
| While working (each edit, each commit) | only the tests for the files you touched: `pytest /tests/<mirror path>` or `make test-for FILE=backend/credits/ledger.py` (maps `backend/x/y.py` to `tests/x/test_y*.py`), and `bun test <file>` | the whole suite, and never `make e2e` per commit |
| End of a phase, or before handing work back | `make check` (the whole suite, about 3 minutes after stage 2) and `make e2e-affected` **once** | `make e2e` (full) |
| Before merging to `main` | `make check`, then the **full** `make e2e`, **once** | merging on a green `e2e-affected` alone |
| On every push (CI) | lint and the whole pytest suite in parallel (`-n auto`), as now | e2e (still needs a browser, not in CI) |

Plus: a test that needs a stack goes in e2e only if no fast test can prove it; a new spec is added to `e2e/spec-map.json` in the same change (the guard test enforces it); a new source folder is mapped or put on the allow-list; the `migration` marker is for one-time data migrations; money, auth and security tests are never deleted without naming the test that covers the same rule (written in `testing.md`, because it is the rule I applied here).

The wording in `CLAUDE.md` changes from "Before finishing any task, run `make check`" to the table above; "Commit only when `make check` passes" stays, because CI reverts a red `main`.

## 8. Decisions I need from you

Please answer by number (for example "1 yes, 2 yes, 3 skip B3 …"). My recommendation is in bold.

1. **Fast password hasher in tests (B1).** **Yes.** One setting under `TESTING`.
2. **`pytest-xdist` with `-n auto --dist worksteal` in `make test` and CI, the `uuid4` parameter fix, and a `make test-serial` for debugging (B2, G9).** **Yes.**
3. **A test-only Postgres service on tmpfs (B3).** **Yes** if you accept one more compose service (`db-test`); no if you want the dev `db` used for everything (then the suite is about 3 min 30 s, not 1 min 50 s).
4. **e2e readiness check and a route warm-up in `make fake-llm` (E3).** **Yes.**
5. **Parallel e2e (E1): a serial `global` project, then a 4-worker `learner` project.** **Yes**, on top of 4. It depends on 4, because without the warm-up the parallel run fails.
6. **e2e wait fixes (E2) and the slimming in section 6 C**: all, none, or pick the rows. **All.** (About 2.5 minutes together.)
7. **Selective e2e:** approve the map in 4.3, the trigger list in 4.2 (anything to add or remove?), the guard test living in `e2e/` and run by `make lint` and CI, and the name `make e2e-affected` with `BASE=main` by default. **Yes to all.** Question inside it: should `backend/graph/**` and `backend/lessons/**` stay as "the six build specs" (my choice), or be triggers (a change to the lesson pipeline runs everything, about 10 minutes)?
8. **Deletions:** section 6 A (17 tests) and section 6 B (2 tests): **delete all**; or name the rows to keep.
9. **Migration tests (6 D):** add a `migration` marker and run them in CI and `make check-full` only (B4). **Yes.** And are all stored lessons and attempts already migrated to the new level names and the first-set record, so the legacy readers' tests can go later? (I did not touch them.)
10. **Gap tests (6 F):** which of G1 to G7 should I write? **G1, G2, G3, G4, G6 now**, G5 and G7 optional. (Each is small; G1 and G2 need real threads and a once-only check that they fail without the lock.)
11. **Coverage:** run a one-off line-coverage report (not a permanent dependency) to back the gap list? **Yes, once.**
12. **The working rules in section 7** into `testing.md` and `CLAUDE.md`, word for word or edited?
13. **Skipped live specs** (`payments-stripe`, `payments-razorpay`): leave as they are (listed as `manual` in the map), or remove the unverified Razorpay one until it has been run against a test account? **Leave.**

Stage 2 will be done on a branch `chore/test-speed`, not pushed, then `make check`, `make e2e-affected` against `main`, and one full `make e2e`, with the new timings beside the old ones.

## 9. Appendix: how the numbers were made

Baseline: `docker compose run --rm backend pytest --durations=60 --junitxml=…` (6,525 passed in 1,010 s, 16:50), each lint and frontend step by its own `docker compose run --rm --no-deps`, and `make e2e` with a timestamp in front of every line of output (57 passed, 612 s). A first cold `make e2e` run failed every spec (the frontend answered 500); the figures above are from the second run, on the same stack after `make e2e-down` and `make fake-llm` brought it up again.

Experiments (nothing saved in the repository; scratch files in the session's scratchpad directory):

- Fast hasher: a scratch settings module `fastsettings` that does `from config.settings import *` and sets `PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]`, mounted at `/fast`, used with `--ds=fastsettings`.
- xdist: `uv pip install pytest-xdist` inside the throwaway container, `pytest -n 8` with a small plugin that makes `uuid.uuid4` deterministic only while tests are collected (standing in for the one-line fix).
- test-only database: `docker run --tmpfs /var/lib/postgresql/data postgres:17-alpine -c fsync=off -c synchronous_commit=off -c full_page_writes=off -c max_connections=300` on the compose network, with `POSTGRES_HOST` pointing at it; removed afterwards.
- parallel e2e: `bunx playwright test --workers=4 <the nine learner specs>` against the running throwaway stack, with and without a one-off warm-up spec (deleted afterwards).
- a throwaway production-build frontend container (removed afterwards; it crashed with `SIGILL` in `next build`).

Two incidental findings recorded for later: the project `.env` sets the database user, name and password, so a scratch database has to be given the same three values; and `pkill -f "playwright test"` inside a command that itself contains that text kills its own shell.
