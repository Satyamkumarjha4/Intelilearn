# Testing

Lesson Crafter is built **test-first**. Every behaviour change starts with a failing test, and every test file says what it tests, why, and which use cases it covers. This document is the contract for both. The object design that makes code testable is in [design.md](design.md).

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
- Frontend unit tests sit beside the file they test as `*.test.ts` and run with `bun test`.
- Sandbox scripts (`sandbox/scripts/*.mjs`) have fixture-driven tests in `sandbox/` (Phase 5–6).
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

The design injects every collaborator through a constructor or `FlowContext` ([design.md §1.2](design.md#12-solid-in-this-codebase)), so tests pass doubles instead of patching.

| Collaborator | Double | Where |
|---|---|---|
| LLM chat models | Fake chat models scripted per call (`raw`, `parsed`, `parsing_error`, exceptions with `status_code`) | `tests/llm_registry/conftest.py` |
| `LLMGateway` in graph tests | `FakeGateway`: scripted outputs per node key (objects, dicts, callables or exceptions), records every call | `tests/support/fakes.py`, with the fixtures in `tests/support/fixtures.py` |
| `CodeSandbox` / `LatexChecker` | `FakeSandbox` returning canned LaTeX and code-check results | `tests/support/fakes.py` |
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
| **Management command** | Exit code and output for success and failure, using `call_command` |
| **Signal receiver** | The observed side effect happens on the triggering save/delete, and not on unrelated ones |
| **Frontend class or util** | Public methods and edge inputs with `bun test`; network via a fake `fetch` |

A new public method without a test is incomplete, as is a branch nobody exercises.

## 6. Markers and suites

| Command | Runs |
|---|---|
| `make test` | All backend tests except `live`, against the docker Postgres |
| `make lint` | ruff and ruff format (backend and tests), OpenAPI validation, eslint, `tsc`, and `bun test` |
| `make check` | `lint` + `test`; required before finishing any task, and run by CI on every push ([ci.md](ci.md)) |
| `pytest -m live` | Golden topics and real provider calls; needs API keys; run by hand only |

## 7. Definition of done

- [ ] The behaviour is described in `docs/`.
- [ ] The test file header lists the use cases, and each has a test.
- [ ] The tests were seen failing before the code existed (or, for a bug, before the fix).
- [ ] No external service is called outside `-m live`.
- [ ] `make check` passes, and the actual result is reported.
