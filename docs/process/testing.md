# Testing

Socra is built **test-first**. Every behaviour change starts with a failing test, and every test file says what it tests, why, and which use cases it covers. This document is the contract for both. The object design that makes code testable is in [design.md](../architecture/design.md).

## 1. Workflow: red → green → refactor

1. **Read the spec.** Find the behaviour in `docs/` (or add it there first).
2. **Write the use cases.** Add them to the header of the matching test file (create the file if needed, see [layout](#2-layout)).
3. **Red.** Write the tests. Run them and watch them fail *for the reason you expect* (an assertion, not an import error or a typo).
4. **Green.** Write the least code that makes them pass.
5. **Refactor.** Clean up the code and the tests while everything stays green.
6. **Check.** `make check` (lint + all tests) before you call the work done or commit.

Run a single file while iterating:

```bash
# -c: with a path outside /app, pytest would otherwise miss backend/pyproject.toml (and the Django settings)
docker compose run --rm backend pytest -c pyproject.toml /tests/core/test_sync.py             # one backend file
docker compose run --rm backend pytest -c pyproject.toml /tests/core/test_sync.py -k profile  # matching tests
docker compose run --rm --no-deps frontend bun test lib/safe-redirect.test.ts
```

By kind of change:

| Change | Tests |
|---|---|
| New behaviour | New tests first, covering the normal case, each edge case and each failure mode |
| Bug fix | First a test that reproduces the bug and fails; then the fix. The test name says what was broken |
| Refactor (no behaviour change) | Existing tests stay green and unchanged except for imports and names. If coverage is thin, add *characterization* tests for current behaviour **before** refactoring |
| Spec change | Update the doc, the use cases in the test header, then the tests, then the code |

## 2. Layout

- Backend tests live in the repo-root `tests/`, mirroring `backend/` one file per module: `backend/core/sync.py` → `tests/core/test_sync.py`, `backend/llm_registry/management/commands/probe_models.py` → `tests/llm_registry/management/commands/test_probe_models.py`.
- A module with a lot of behaviour may split into several files named by area: `tests/accounts/test_views.py` and `test_views_profile.py`.
- The staff console (`backend/console/`) is tested by area in `tests/console/` (`test_overview.py`, `test_usage.py`, `test_runs.py`, `test_registry.py`, `test_routing.py`, `test_flow_settings.py`, `test_learners.py`, `test_audit.py`, `test_access.py`). Its fixtures are in `tests/console/conftest.py`: a frozen clock (`now`), `make_call` for `ModelCall` rows at known times, `registry` for providers and models, and `count_queries`. A list endpoint gets a test that its query count is the same for few and many rows, and `test_audit.py` has a guard that fails when a console endpoint that changes something is added without an audit test.
- Frontend unit tests sit beside the file they test as `*.test.ts` and run with `bun test`.
- Sandbox scripts (`sandbox/scripts/*.mjs`) are tested through `SandboxRunner` in `tests/graph/test_sandbox.py`, against fixtures in `sandbox/fixtures/` (`good/` must pass; each `bad/` file names the rules it must trigger in an `// expect:` header). The Node package is part of the backend image, so these run in `make test`.
- Shared builders and doubles live in `tests/support/` (importable as `support.…`; `tests/` is on the test python path) and its fixtures are registered for every test from `tests/conftest.py`. A graph run executes nodes on LangGraph's worker threads, whose database connection only sees committed rows, so tests that run a whole graph or the runner are marked `django_db(transaction=True)`.
- Fixtures: shared ones in `tests/conftest.py`; ones used by one package in that package's `conftest.py` (for example the registry rows and fake chat models in `tests/llm_registry/conftest.py`). Every fixture has a docstring when its purpose isn't obvious from its name.

## 3. Documenting tests

### 3.1 The file header (required)

Every test file starts with a docstring (Python) or block comment (TypeScript) with three parts:

- **Unit under test**: the class or module, and one line on what it does.
- **Why**: what would go wrong for the product if this broke. This is what tells a reader which tests must never be deleted.
- **Use cases**: one bullet per behaviour the file covers, in the order of the tests. Every bullet has at least one test, and every test belongs to a bullet. When you add, remove or rename a test, update the list in the same change.

```python
"""Unit under test: `core.sync.DatabaseSyncer`, the insert-only copy of local rows to Supabase on every backend start.

Why: it writes to the shared database unattended. Overwriting, duplicating or mis-ordering rows would corrupt
real user data, and a sequence left behind would make the next insert on Supabase fail.

Use cases:
- copies rows that the target is missing
- copies a user's profile together with the user (foreign-key order)
- is a no-op on the second run
- never overwrites rows that already exist on the target (insert-only)
- reports a unique-constraint clash instead of raising, so startup continues
- carries many-to-many links along with their object
- resets primary-key sequences so new rows on the target don't collide
"""
```

```ts
/**
 * Unit under test: `RedirectPolicy.safeNext`, which decides where `/auth?next=…` may send a user after sign-in.
 *
 * Why: an open redirect after sign-in lets a phishing link bounce a real user to an attacker's site.
 *
 * Use cases:
 * - keeps same-site paths, including query and hash
 * - rejects protocol-relative, backslash, tab-smuggled and absolute URLs
 * - rejects non-string input (missing or repeated query parameter)
 */
```

### 3.2 Each test

- **The name states the behaviour and the expected outcome**, in the domain's words: `test_login_is_limited_per_account_across_addresses`, `test_falls_back_to_next_model_after_fatal_error`. Not `test_login_2` or `test_gateway`.
- **One behaviour per test**, laid out as arrange → act → assert, with a blank line between the parts.
- **Add a docstring or a comment only for the *why*** that the name can't carry: a regression (`# Regression: refresh rotated the cookie without blacklisting the old token`), a non-obvious set-up, or a protocol quirk.
- **Table-driven** cases (`@pytest.mark.parametrize`, `test.each`) for rule sets such as validators, routing thresholds and redirect inputs. Give each case an `id` that reads as a use case.

## 4. Test doubles

The design injects every collaborator through a constructor or `FlowContext` ([design.md §1.2](../architecture/design.md#12-solid-in-this-codebase)), so tests pass doubles instead of patching.

| Collaborator | Double | Where |
|---|---|---|
| LLM chat models | Fake chat models scripted per call (`raw`, `parsed`, `parsing_error`, exceptions with `status_code`) | `tests/llm_registry/conftest.py` |
| `LLMGateway` in graph tests | `FakeGateway`: scripted outputs per node key (objects, dicts, callables or exceptions), records every call | `tests/support/fakes.py`, with the fixtures in `tests/support/fixtures.py` |
| `CodeSandbox` / `LatexChecker` | `FakeSandbox` returning canned LaTeX and code-check results | `tests/support/fakes.py` |
| Question batches from a model | `ScriptedQuestions` (`tests/support/question_data.py`): answers `test.generate` with one question per line of the prompt, in order, and can spoil one answer on purpose (a wrong difficulty, a repeated text) to drive the retry and the second round | `tests/support/question_data.py` |
| The action gate | `CountingGate`, `RefusingGate`, `SharedCountingGate` (the last for views, which reach the gate through the `ACTION_GATE` setting) | `tests/support/gates.py` |
| The credit gate in a test | `credits_on` (fixture): switches `ACTION_GATE` to `CreditGate`, makes sure the plan's prices are in the table (`PriceSeed`: a `transaction=True` test flushes the migration's rows) and gives back a `CreditsOn` with `fund(user, n)`, `balance`, `reserved` and `holds`. The autouse `_pin_the_open_gate` starts every other test on `OpenGate` whatever the default becomes; a test that wants another gate sets `ACTION_GATE` itself, as the gate tests have always done | `tests/support/credits_fixtures.py` |
| Payments in a test | `payments` (fixture): registers `ScriptedGateway`, switches it on as the only (default) gateway with a known secret, puts the plans in the table, and gives back a `Payments` with `buy(...)` (a pending order the way the API makes it), `send(kind, order, ...)` (a signed event to the processor), `post(client, kind, order, signed=...)` (the same through HTTP), `says_paid(order)` / `says(order, state)` (what `fetch_status` will answer) and `script` (every call the gateway received, and errors to raise). A test never calls a real provider | `tests/support/payments.py` |
| Earning in a test | `earning_on` (fixture): `credits_on` plus `CreditsActivitySink`, so studying earns the daily credit and the streak; kept apart from `credits_on` so the tests that count credits exactly are not moved by the day's credit. A test drives the streak by sending activity at instants (`sink.record(user, kind, at)`) with a `FakeClock`, never by sleeping | `tests/support/credits_fixtures.py` |
| The plans in a test | `PlanSeed().apply()` (an autouse fixture in the plan test files): the four plans of the spec, re-added after a `transaction=True` test has flushed the migration's rows. A test buys with `PurchaseDesk(ledger=…).open(…)` then `PlanFulfilment(ledger=…).fulfil(…)` on a `FakeClock` ledger and moves the clock to start the next week | `credits/plans/seed.py` |
| The pricing matrix | `MATRIX` and `JOURNEYS`: every row of the plan's §5.4 and §5.5 as `(action, size, credits, price keys)`, built from the real services' `size_of`, shared by the rule tests, the quote-equals-gate test and the endpoint | `tests/support/pricing_matrix.py` |
| The clock of the credits app | `FakeClock` (`now()`, `set()`, `advance(days=…)`): time stands still until the test moves it. `credits` has no other source of "now", so an expiry, a window or a day boundary is tested by moving the clock, never by sleeping | `tests/support/clock.py` |
| The activity sink | `CountingActivity` (records user, kind and instant of each `record`) and `RaisingActivity` (to show a broken sink cannot undo a submit) | `tests/support/activity.py` |
| Event publisher, task queue | A list-backed publisher and `RecordingQueue` (`LESSON_TASK_QUEUE` points the API at it) | `tests/lessons/test_runner.py`, `tests/support/fixtures.py` |
| The real gateway and LangChain client | `tests/e2e/fake_llm_server.py`, a fake OpenAI-compatible server run in a thread | `tests/e2e/` |
| HTTP (media sources) | `httpx.MockTransport` with recorded responses | per test file |
| Sleep, clock, rate limiter | Plain callables or fakes recording the delays | per test file |
| Redis cache | The real test Redis, cleared around every test (`_clear_cache` in `tests/conftest.py`) | — |
| Database | The real docker Postgres via `pytest-django` (never Supabase) | — |

Rules:

- **Prefer fakes over `mock.patch`.** Patch only framework-level values that can't be injected (settings, throttle rate tables) and use `monkeypatch` so it's undone.
- **Never call an external service.** LLM providers, Wikimedia, Openverse and Giphy are always faked. Real calls run only under `pytest -m live`, which is never part of `make check`.
- **Real client construction is fine offline.** `tests/llm_registry/test_providers.py` builds each LangChain client without calling it, to prove parameter names.
- Build shared fakes once in a `conftest.py`; don't copy them between files.

## 5. What to test per kind of class

| Kind | Must cover |
|---|---|
| **Value object / Pydantic schema** | Valid construction, each constraint rejecting bad input, `model_validator` rules, serialization round trip |
| **Django model** | `clean()` rules, custom methods (`is_complete`, `advance_to`), manager/queryset methods (`owned_by` hides other users' rows), constraints (`unique_together`) |
| **Service** | Each public method's success path, each failure it raises, and the side effects it promises (rows written, tasks enqueued via a fake) |
| **View** | Status codes for success, validation error, unauthenticated, wrong owner (`404`), throttled, and conflict cases; response shape; CSRF where it applies. The OpenAPI schema is validated by `make lint` |
| **Strategy / policy** (`RetryPolicy`, `ProviderProfile`, `RoutingPolicy`) | Every branch, table-driven; boundaries of thresholds (for example 2 and 3 correct for the prerequisite route) |
| **Validator** | One failing fixture per rule, built from real bad LLM output where possible, plus one fully valid fixture that yields no problems |
| **Adapter** (`SandboxRunner`, `MediaSource`) | Mapping of external responses to our types, error translation, "no results" behaviour, against faked transports |
| **Graph node** | Given a state and scripted `FakeGateway` output, the returned state update and emitted events; `AwaitNode` has no side effects |
| **Router** | Every outgoing edge, table-driven |
| **Graph** (end to end) | The node path taken, interrupts, resume with `Command(resume=…)`, targeted regeneration, degrade paths, final state |
| **Money movement** (`credits.ledger.Ledger`) | Each method's rows and amounts, a repeated key changing nothing, every refusal writing nothing, the invariant (the ledger equals the buckets) after seeded random walks of hundreds of movements, and **real threads** (`django_db(transaction=True)` with a barrier) for concurrent holds, a hold racing an expiry, concurrent first movements and a repeated key. A concurrency test should fail when the lock is removed; check that once when you write one |
| **Management command** | Exit code and output for success and failure, using `call_command` |
| **Signal receiver** | The observed side effect happens on the triggering save/delete, and not on unrelated ones |
| **Payments** (`tests/payments/`) | The order state machine on every path (`test_order_events.py`: a duplicate event once, an unknown order, an amount or currency mismatch, a late success after expiry, a failure, full and partial refunds adding up exactly, a shortfall, a dispute, a plan's unstarted weeks cancelled first, a revoked bucket not refilled by a late release), the checkout, the endpoints, the webhook door (`test_webhook_view.py`: a bad signature makes **no query**, 413, 404, no sign-in or CSRF), the reconciler, the admin refund, and **real threads** for a webhook racing the reconciler. Everything runs against `ScriptedGateway` (`tests/support/payments.py`), which subclasses the real `PaymentGateway`, so it proves the port can be implemented by something other than the shipped fake **Stripe** (`test_stripe_gateway.py`, `test_stripe_events.py`, `test_order_events_by_payment.py`, `test_safety_checks.py`): `httpx.MockTransport` with bodies shaped as Stripe documents them: the request (form-encoded, paise, INR, the order id as `client_reference_id` and in both metadata, the return URLs, an expiry inside Stripe's window, the pinned `Stripe-Version`, Basic auth, the order id as `Idempotency-Key`), the answer mapped (a redirect; `paid`, `pending` and `expired` from the session), a refund, and every failure (no connection, timeout, 5xx, 429, 409 are unavailable; 400, 401, 403 are rejected; no key in any message; a refused key told by Stripe's code); the signature (a computed header, a vector computed outside the code, several `v1`, a `v0` beside it, a wrong secret, an altered body, an old or future timestamp, a missing, unreadable or v0-only header, an empty secret); each event mapped (paid and unpaid completions, delayed success and failure, expiry, a refund by its own amount and event id, a pending or failed refund ignored, `charge.refunded` ignored, a dispute) and unrelated events ignored; an order found by its payment reference; and the two start-up checks (`payments.E004`, `payments.E005`) for every key kind. |
| **Frontend class or util** | Public methods and edge inputs with `bun test`; network via a fake `fetch` |
| **Notices and the credit screens' words** | `credits.notices.ExpiryNotices` is tested pure (`of(buckets, now, zone, settings)`) for every source and window edge, the learner's day, the sum of one day, and the words, then through the database; the frontend's `lib/credits/` classes (`CostSizes`, `QuoteClient`, `CostWords`, `WalletWords`, `StreakView`, `PlanWords`, `HistoryWords`, `NoticeDismissals`) are tested with a fake API and fixed dates, never the browser's clock or locale (`ShortDate` exists because `Intl` puts a comma after the weekday in some locales) |

A new public method without a test is incomplete, as is a branch nobody exercises.

## 6. Markers and suites

| Command | Runs |
|---|---|
| `make test` | All backend tests except `live`, against the docker Postgres |
| `make lint` | ruff and ruff format (backend and tests), OpenAPI validation, eslint, `tsc`, and `bun test` |
| `make check` | `lint` + `test`; required before finishing any task, and run by CI on every push ([ci.md](ci.md)) |
| `make e2e` | The Playwright smoke tests in `e2e/` against a throwaway stack on the fake LLM (see below). Needs a browser, so it is **not** part of `make check` or CI yet |
| `make payments-live` | `pytest -m payments_live`: `tests/payments/test_stripe_live.py` creates a real **test-mode** Stripe Checkout Session, asks about it and expires it (no payment). Skipped without `STRIPE_SECRET_KEY=sk_test_...`; a key that Stripe refuses (expired, rolled) fails with Stripe's reason. Never part of `make check`: it needs a key and the network |
| `make e2e-payments` | `e2e/tests/payments-stripe.spec.ts` on a stack where Stripe is the only way to pay: a browser pays on Stripe's own page with the test card and the return page's status fetch fulfils the order (no webhook, no tunnel). Refuses to start without `STRIPE_SECRET_KEY=sk_test_...` in `.env`; `make e2e` skips the spec |
| `pytest -m live` | The live suite in `tests/live/`, against the real models, sandbox and media services. Two files: the **golden topics** (three topics from a first question to a ready lesson and a graded test, held to structural checks and a cost budget, `LIVE_MAX_COST_USD`, default 2.00) and the **question quality** checks of phases 9.1 to 9.7 (see below). **It spends money with the keys in `.env`** (`GEMINI_API_KEY` for the default registry, `GROQ_API_KEY` for its fallback) and is deselected by default (`addopts = -m 'not live'`); run it by hand. The checks it applies (`tests/live/golden.py`) are tested offline in `make check` |

### 6.0 The live suite

`tests/live/golden.py` holds *pure* checks that read stored data and list what is wrong in plain words, so a failed live run says what to look at; `tests/live/test_golden_checks.py` tests those checks offline. `test_golden_questions.py` applies them to what a real model really wrote:

- `topic.traits` judges calculation, programming and history topics the way a person would;
- `lesson.plan` sets `quantitative` for a calculation topic and not for a history topic;
- the calibration pool has two valid multiple-choice questions in each of the five bands;
- a quiz of every kind the topic offers: multiple-select questions have two or more right options, numerical expressions evaluate to their stored answer, short and long answers have criteria that add up to their marks;
- a retake does not ask again, in other words, what the first try asked (word overlap just under the product's own threshold);
- on a real lesson (made from a self-rating, the cheapest way): its test, a quiz made from it and its concept index name only the lesson's own concepts, and its revision sheet covers the concepts by the product's rule.

A live run needs a model key with a quota to match: the default registry's Gemini models on a free key allow about 20 requests a day each, which one lesson uses up. The results of each run, and the changes they suggest, are recorded in the roadmap's phase 9 block.

### 6.1 Browser tests (`make e2e`)

`e2e/` is its own bun package (`@playwright/test`), apart from `sandbox/`, which is the lesson runtime. `make fake-llm` starts a separate compose project, `socra-e2e` (`docker-compose.e2e.yml`): its own containers and database volume, ports `E2E_FRONTEND_PORT` / `E2E_BACKEND_PORT` (7100 / 7110), **no Supabase URL and no provider key**, throttles raised so a run can sign up many learners, and the registry from `tests/e2e/fake_registry.json`, whose only model is `tests/e2e/fake_llm_server.py`. It also creates the staff user (`E2E_STAFF_EMAIL` / `E2E_STAFF_PASSWORD`). `make e2e` runs that and then the specs; `make e2e-down` deletes the stack. The first time: `cd e2e && bun install && bunx playwright install chromium`.

Since phase 10.6 the stack also enables **the fake payment gateway** (`PAYMENT_ALLOW_FAKE_GATEWAY=true`, `PAYMENT_GATEWAYS_ENABLED=fake`, a secret from the environment): a spec buys through the real screens, and plays the provider with `e2e/support/provider.ts`, which signs a callback and sends it to `/api/payments/webhooks/fake` **through the frontend's address** (so the proxy is shown to keep the raw body and the signature header). `payments.spec.ts` covers one-time credits and a plan, a return page and a forged or mismatched callback that grant nothing, a refund, and a learner too poor for the rest of a lesson who buys, comes back and sends the answers that were kept.

Since phase 10.5 the stack **charges and earns for real**: `docker-compose.e2e.yml` sets `ACTION_GATE` to the credit gate and `ACTIVITY_SINK` to the credits sink (the dev default stays the open gate and the do-nothing sink until phase 10.9), and `make fake-llm` makes the daily credit large, so a spec that builds several lessons for one learner is never short once it has studied. The signup grant is left at 30 on purpose: the credits specs read it. A spec that needs credits somewhere specific (a bucket about to run out, a learner nearly empty, a gift to carry on after a refusal) seeds it with `e2e/support/seed.ts` (`Seed.grantExpiring`, `Seed.give`, `Seed.leave`), which runs the same `Ledger` an administrator's action does in a Django shell in the backend container (`make e2e` passes the compose command in `E2E_COMPOSE`). `credits.spec.ts` checks that the price on the new-lesson form is what the history says was reserved (read from the history, never from the balance, so a daily credit cannot confuse it), that the wallet, the history and the header chip say what the API says, that the streak screen shows today's study, that a Quick check handed in too poor keeps its answers and carries on after a gift, that a learner who cannot pay is told beside the button and the refusal offers the way to buy, that notices appear for a bucket in its window and can be put away for the day, and that the credit screens do not scroll sideways at 400px.

Each spec has a header with what it covers and why, like a unit test. They cover the seams the unit tests cannot: the learner's whole path from sign-up to a test that can be tried again with new questions (an attempt that is over is `409 attempt_sealed`, the old single call is gone, and the questions never carry the answers), the landing page's question, who may open the console, a refresh on the last onboarding step, and Stop then Retry at four different moments of a build. Because every model answer is canned, a lesson builds in seconds and nothing here proves the lessons are good: that is `pytest -m live`. `followups.spec.ts` covers the three follow-up cases (a failed test offers a Foundation lesson once and a second failure offers to open it, two requests at once make one lesson, an excellent result offers an Advanced lesson, a low rater who fails sees only a note). `self-rating.spec.ts` covers rating yourself (the star radios with the keyboard, a Beginner whose prerequisites are planned and an Expert who has none, a self-rated build that is stopped and retried), what `POST /lessons` refuses, and the choice after a perfect quick check: the two options, the Expert lesson with a test, and the two sheets with none. `sheets.spec.ts` covers study sheets: from a topic by quick check (any score, both sheets, no lesson and no test) and by rating yourself (no quiz, nothing planned), one sheet then the other on a ready lesson, a page that was out of date opening the sheet that exists instead of making another, and a sheets-only lesson being asked for its missing sheet and refused a follow-up. `quizzes.spec.ts` covers quick quizzes: a topic quiz with calibration then a retake (new questions), a quiz from two lessons using their existing scores, a 5-question quiz that cannot pick short or long answers, and a topic quiz that leads to making a lesson. A quiz from a lesson answered wrong checks that each weak concept's "Study this" link opens the page of the lesson that teaches it (the Introduction for one concept, the Core page for another).

## 7. Definition of done

- [ ] The behaviour is described in `docs/`.
- [ ] The test file header lists the use cases, and each has a test.
- [ ] The tests were seen failing before the code existed (or, for a bug, before the fix).
- [ ] No external service is called outside `-m live`.
- [ ] `make check` passes, and the actual result is reported.
