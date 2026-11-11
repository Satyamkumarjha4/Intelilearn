# Socra: development instructions

An AI tutor that diagnoses what a learner knows, then generates a lesson or study sheet. The specification lives in `docs/` (index: `docs/README.md`). Read the relevant doc before changing behaviour, and update it in the same change when behaviour changes. `docs/process/roadmap.md` tracks progress by phase: tick items off as they land. How code is structured is in `docs/architecture/design.md`; how it is tested is in `docs/process/testing.md`.

## Stack and tooling (no substitutes)

- **Backend**: Django 5.2 + DRF + Celery in `backend/`, managed with **uv** (`uv add`, `uv run`). Never use pip or requirements files.
- **Frontend**: Next.js 16 in `frontend/`, managed with **bun** (`bun add`, `bunx`). Never use npm, yarn, or pnpm. Next 16 differs from older versions (for example, `middleware.ts` is now `proxy.ts`): follow `frontend/AGENTS.md` and check `frontend/node_modules/next/dist/docs/` before writing frontend code.
- **Running**: Docker Compose (`make up`). Services: `db` (Postgres), `redis`, `backend`, `worker`, `beat` (the scheduler; exactly one), `frontend`. `make help` lists every command.
- After adding a dependency, rebuild with `docker compose up --build`.

## Configuration

- **Every** port, host, name, password, key, and URL comes from the environment, through the single root `.env` (template: `.env.example`). This covers Django settings, `docker-compose.yml`, and `next.config.ts`.
- Every variable has a working development default, so the stack and tests run with no `.env` (CI). Use `env("X", default=...)` in Django and `${X:-default}` in compose.
- To add a variable: add it to `.env.example` with a comment, and to compose if containers need it. Never hard-code the value anywhere.
- Never print, log, or commit secrets. Don't read `.env` values into output; grep variable names only if needed. `.env` and `token` are gitignored.

## Database

- There is no Supabase URL by default, so the app uses the docker `db` Postgres. When `SUPABASE_DATABASE_URL` is set, Supabase becomes `default`, and on every backend start `manage.py bootstrap` migrates both databases and copies local rows that Supabase lacks. The copy is insert-only and never overwrites (`backend/core/sync.py`).
- Schema changes go through Django migrations only (`make makemigrations`). Never edit tables in the Supabase dashboard.
- Tests always run against the docker Postgres, never Supabase (`TESTING` in settings).

## LLM calls

- Never hard-code a model, provider, or parameter. Every LLM call goes through `llm_registry.gateway.Gateway().invoke(node_key, ..., snapshot=...)`, with a node key from `llm_registry/node_specs.py`.
- A new LLM step means a new `NodeSpec`, then `migrate` creates its config. Bind models in the admin or in `llm_registry/seed.py`.
- Tests use fake chat models, never real APIs (see `tests/llm_registry/conftest.py`).

## API conventions

- API paths have **no trailing slash** (`/api/lessons`). The Next.js `/api` proxy depends on it.
- Every endpoint has `@extend_schema` (tags, summary, request and response schemas), so Swagger at `/api/docs` stays accurate.

## Design: object-oriented and SOLID

`docs/architecture/design.md` is the binding object model: rules, layers, the pattern used in each module, and UML class diagrams for the current code and every roadmap phase. Read the section for the module before changing it.

- **All behaviour lives in classes**, each with one responsibility. Ports are `typing.Protocol`s, shared algorithms are `abc.ABC` bases (Template Method), and results are frozen dataclasses or Pydantic models. No new module-level functions holding logic.
- **Framework hooks are the only exception**, and stay thin: signal receivers, system checks, Celery tasks, the DRF exception handler, LangGraph reducers, `settings.py`/`urls.py`/migrations, pytest functions, and React components/hooks. Each just builds or looks up an object and calls one method on it.
- **SOLID**: views parse and format, services decide, adapters do I/O (S). Add a variant as a new class registered in a registry, never a new `if kind ==` branch (O). Implementations honour the port's contract, including errors and empty results (L). Depend on small ports, not whole objects (I). Inject collaborators through constructors with production defaults; `default_context()` is the graph's composition root (D).
- **Use the pattern the design names** for the module (for example `Strategy` for provider profiles and validators, `Template Method` for graph nodes and prompts, `Facade` for the gateway). A new class, collaborator, or pattern goes into `docs/architecture/design.md` in the same change.
- Code that predates the design is listed in the **refactor backlog** in `docs/architecture/design.md`. Close an item when you next touch that module, behaviour-neutral and with tests green before and after, and tick it off.

## Tests: test-driven

`docs/process/testing.md` is the testing contract. In short:

- **Test first**: write the use cases, then failing tests (see them fail for the right reason), then the code, then refactor while green. A bug fix starts with a test that reproduces it. A refactor keeps the existing tests green and unchanged.
- Tests live in the repo-root **`tests/`**, mirroring `backend/`. For example, `backend/core/sync.py` is tested in `tests/core/test_sync.py`, and `backend/config/databases.py` in `tests/config/test_databases.py`. Frontend tests sit beside their file as `*.test.ts` (`bun test`).
- **Every test file starts with a header**: the unit under test, *why* it matters, and a bulleted list of the use cases it covers. Each use case has a test and each test belongs to a use case; update the list whenever tests change. Test names state the behaviour and outcome.
- Every change to behaviour comes with tests in the matching path; every new public method and every branch is exercised.
- Use injected fakes (fake chat models, `FakeGateway`, `httpx.MockTransport`) over `mock.patch`. Never call external services (LLMs, media APIs); only `pytest -m live` may.
- **What to run, and when** (the full rules are in `docs/process/testing.md` 6.2): while working, only the tests for the files you touched (`make test-for FILE=backend/x/y.py`, `bun test <file>`), never the whole suite and never `make e2e` per commit. At the end of a phase, or before handing work back, `make check` and `make e2e-affected` **once**. Before merging to `main`, `make check` and then the full `make e2e` **once**. CI runs lint and the whole suite on every push.
- **Report the actual results.** Every report states which e2e specs ran and why (from `make e2e-affected`'s printout), or says that e2e was not run. If something fails, say so and show the output. Never describe work as done while checks fail.
- A new e2e spec is added to `e2e/spec-map.json` in the same change (a guard test fails otherwise); a new source folder is mapped or named in `e2e/spec-map.test.ts`. Never delete a test that protects money, payments, auth, the ledger or security without naming the test that covers the same rule.

## Git

- Never commit directly to `main`. Branch per piece of work: `phase-<n>/<topic>` (for example `phase-1/auth`), `fix/<topic>`, or `refactor/<topic>`.
- Use Conventional Commits: `feat(accounts): cookie JWT login`, `fix(sync): reset sequences`, `refactor(gateway): extract RetryPolicy`, `docs: …`, `test: …`, `chore: …`. Keep each commit to one logical change; a `refactor` commit changes no behaviour.
- Commit when the tests for the files you touched pass. CI (`docs/process/ci.md`) runs the same checks as `make check` on every push: a failing push to `main` is **reverted automatically**, and a failing branch gets a `ci-failure` issue that closes when it goes green. So never push, and never merge to `main`, without a green `make check` (and, before a merge, the full `make e2e`).
- Never commit `.env`, `token`, keys, or generated media.
- Commit, push, or open PRs only when asked. Never force-push, rewrite pushed history, or skip hooks (`--no-verify`).

## Code style

- Python: ruff, line length 120, over `backend/` and `tests/` (`make lint`). Frontend: eslint and `tsc` (run with `next typegen` first).
- Match the surrounding code's naming, structure, and comment density. Comments explain *why*, not *what*.

## UI design system

The approved mockup, `docs/design/mockups/socra-mockup.html`, is the visual source of truth for every screen. Ignore its dashed "Mockup controls" bar (palette, theme and screen chips): that is not product UI.

- **Token mapping** (mockup → app, defined in `frontend/app/globals.css`): `--brand`→`primary`, `--brand-deep`→`primary-deep`, `--brand-soft`→`primary-soft`, `--brand-text`→`primary-text`, `--on-brand`→`primary-foreground`, `--alt`→`marigold`, `--alt-deep`→`marigold-deep`, `--alt-soft`→`marigold-soft`, `--alt-text`→`marigold-text`, `--tri`→`insight`, `--tri-soft`→`insight-soft`, `--tri-text`→`insight-text`, `--ok*`→`success*`, `--bad*`→`destructive*`, `--surface`→`card`, `--surface-2`→`muted`, `--line`→`border`, `--muted`→`muted-foreground`, `--fg`→`foreground`, `--bg`→`background`, `--paper`→`paper`. Use tokens, never raw colours.
- **Colour roles**: `primary` (teal) is the main action, progress and the current step. `marigold` is secondary calls to action, "waiting for you" and things to learn. `insight` (grape) is anything the AI says about the learner: assessment, level, key ideas, AI feedback. `success` / `destructive` mean right / wrong.
- **Brand**: the product is **Socra**. Use `components/brand/logo.tsx` (`variant` full or mark, `size` sm, md or lg) wherever the name or mark appears; the favicon is `app/icon.svg`. Never hard-code the old name "Lesson Crafter" in anything a person can see.
- **Fonts**: headings use the heading font (Fredoka), body text Nunito, and mono for counts and labels.
- **Buttons**: use the chunky pressable variants in `components/ui/button.tsx`. Never hand-roll button styles.
- **Icons**: `lucide-react` only. The mockup's inline SVGs are placeholders for lucide icons.
- **Copy**: plain, warm and encouraging, written for school and college students. Never show internal terms (node, run, graph, pipeline, stage, LLM, model) to learners. "Credits" is a plain word a learner may see (what lessons cost and what they hold); never show hold, ledger, bucket, reserve, gateway, webhook, order state or settle ("being used for lessons being made" says what a reserve is). "Quick check" is the diagnostic quiz at the start of a lesson (and "Basics check" its prerequisite part); "Quick quiz" is the practice quiz on a topic or on lessons; "Test" is the lesson's test, which can be taken again (never "final", never "one attempt").
- **Layout**: desktop-first, and it must work at 400px wide with no horizontal scroll.
- **Accessibility**: visible focus, `aria-label` on icon buttons, keyboard support, and respect `prefers-reduced-motion`.
- **Engineering**: keep logic in pure `lib/` domain classes, unit-tested with `bun test`; components stay thin. Don't change API contracts unless the task says so.
- **Every UI task ends with** type check, lint and `bun test`, then a short summary of the files changed and any open questions.
