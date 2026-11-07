# Socra docs

Start here. The docs are grouped by what you are trying to do. Status marks: ✅ current as far as checked · ⚠️ partly out of date (the "Still open" section at the bottom says what) · 🗄️ historical, kept for the record. What was corrected in the last review, and what is still open, is at the bottom.

## Where to look

| I want to… | Read |
|---|---|
| Run the app on my machine | [getting-started/local-setup.md](getting-started/local-setup.md) |
| Understand what Socra does and how the pieces fit | [architecture/overview.md](architecture/overview.md) |
| Know the code rules before changing something | [architecture/design.md](architecture/design.md) (binding object model) and the repo-root `CLAUDE.md` |
| Change the lesson flow or a prompt | [architecture/lesson-graph.md](architecture/lesson-graph.md) |
| Add or rebind an LLM model or step | [architecture/model-registry.md](architecture/model-registry.md) |
| Add or change a table | [architecture/data-model.md](architecture/data-model.md) |
| Call or change an API endpoint | [reference/api.md](reference/api.md) (Swagger at `/api/docs` is the source of truth for shapes) |
| Change a screen | [reference/frontend.md](reference/frontend.md), then the mockups in [design/mockups/](design/mockups) |
| Change the first-topic suggestions | [reference/onboarding.md](reference/onboarding.md) |
| Write or run tests | [process/testing.md](process/testing.md) |
| Understand CI and the auto-revert on `main` | [process/ci.md](process/ci.md) |
| See what is done and what is left | [process/roadmap.md](process/roadmap.md) |

## Everything, by folder

### getting-started/
| Doc | What it is | Status |
|---|---|---|
| [local-setup.md](getting-started/local-setup.md) | Docker Compose setup, `.env`, databases, running a lesson from the terminal, the fake-LLM walkthrough, troubleshooting | ✅ |

### architecture/ (how it is built)
| Doc | What it is | Status |
|---|---|---|
| [overview.md](architecture/overview.md) | What the product does, components, lifecycle, resilience layers, security | ✅ |
| [design.md](architecture/design.md) | The binding object model: rules, layers, patterns, per-module class diagrams, refactor backlog (1,700+ lines, with a contents list at the top) | ✅ |
| [lesson-graph.md](architecture/lesson-graph.md) | The LangGraph flow: diagnose → author → build and verify, with every validation, retry and fallback | ✅ |
| [model-registry.md](architecture/model-registry.md) | Providers, models, node specs, reasoning, structured output, the gateway, the admin | ✅ |
| [data-model.md](architecture/data-model.md) | Tables and fields, stages, access rules, what a lesson delete removes | ✅ |
| [credits-system.md](architecture/credits-system.md) | The feature spec of credits and payments (phase 10): what things cost, how credits are earned, bought, spent, refunded and expire, the console and the legal words. What the product does and why; the code is in design.md §4.26 and §4.27 | ✅ |
| [modular-lessons.md](architecture/modular-lessons.md) | The feature spec of the modular lesson parts (phase 9): self-rating, retakes, follow-ups, sheets, quick quizzes, concept links. What the product does and why; the code is described in the docs above | ✅ |

### reference/ (what it exposes)
| Doc | What it is | Status |
|---|---|---|
| [api.md](reference/api.md) | REST and SSE reference, errors, rate limits, the staff console API | ✅ |
| [frontend.md](reference/frontend.md) | Pages, the stage-driven lesson view, sandbox runtime, design system, the console screens | ✅ |
| [onboarding.md](reference/onboarding.md) | How the four first-topic suggestions are chosen, cached and kept from ever blocking the learner | ✅ |

### process/ (how we work)
| Doc | What it is | Status |
|---|---|---|
| [testing.md](process/testing.md) | The test-first contract, file headers, test doubles, markers, browser tests | ✅ |
| [ci.md](process/ci.md) | The workflow, auto-revert on `main`, failure issues for branches | ✅ |
| [roadmap.md](process/roadmap.md) | Open work first, then the finished phases. Tick items off as they land (a `CLAUDE.md` rule) | ✅ |

### design/ (visual source of truth)
| Item | What it is | Status |
|---|---|---|
| [mockups/socra-mockup.html](design/mockups/socra-mockup.html) | The approved learner-facing mockup (every screen) | ✅ |
| [mockups/socra-admin-mockup.html](design/mockups/socra-admin-mockup.html) | The staff console mockup | ✅ |
| [pending-screens.md](design/pending-screens.md) | Every screen phase 9 built without a mockup, grouped by flow, for a design session | ✅ |

### legal/
| Doc | What it is | Status |
|---|---|---|
| [README.md](legal/README.md) | Where the privacy, terms and contact words live (`frontend/content/legal/`), the owner's note, and what to update when they change | ✅ |

### archive/ (finished, kept for the record)
| Item | What it is | Status |
|---|---|---|
| [ui-audit-2026-10-25.md](archive/ui-audit-2026-10-25.md) | The screen-by-screen UI audit and its fixes | 🗄️ |
| [credits-implementation-plan.md](archive/credits-implementation-plan.md) | The plan phase 10 was built from: the decisions (D1 to D21 and T1 to T36), the places the spec was changed, the changelog of every phase (P1 to P16) and the risks | 🗄️ |
| [modular-lessons-implementation-plan.md](archive/modular-lessons-implementation-plan.md) | The plan phase 9 was built from: the decisions (D1 to D24), the places the spec was changed, the changelog of every phase (C1 to C41 and on) and the risks. Read it to learn why something is the way it is | 🗄️ |
| `ui-audit-screenshots/` | About 30 MB of audit screenshots. Gitignored, so it only exists on the machine that took them | 🗄️ |

## What changed in the last review

The docs were checked against the code on 26 October 2026 and the stale parts were corrected.

| Doc | What was fixed |
|---|---|
| [reference/api.md](reference/api.md) | The `X-Forwarded-For` paragraph now says the per-address limits can be bypassed by a client that sends its own header. Added the missing console fields (`daily_activity`, `previous_finished`, `calls` and `spend` per model), `range=custom` with `start` and `end`, and the port wording. |
| [architecture/data-model.md](architecture/data-model.md) | Staff are described. Added `is_active` and the terms fields on `User`, the conventions (empty strings not NULL, plain `varchar` choices, no database `ON DELETE`), the real `QuizResult` and `GraphRun.payload` shapes, the missing `MediaAsset`, `LessonVersion` and `ModelCall` columns, and a "Deleting a lesson" section that says what is not removed. |
| [architecture/overview.md](architecture/overview.md) | Postgres is drawn as the docker `db` or Supabase. Keys are in the root `.env`. The console's model probe is named as the one place a request calls a model. The Supabase lock-down is described as not yet in place. |
| [getting-started/local-setup.md](getting-started/local-setup.md) | Supabase is marked optional. The `enable_rls.sql` instruction (the file does not exist) is replaced by what to do by hand. Added the six missing environment variables, the `/console` URL and the console's usage page. Removed "Later phases add". |
| [architecture/design.md](architecture/design.md) | The pattern table matches the code. The backlog intro is current, two real gaps are listed as open (module-level helper functions that hold logic, and `if kind ==` chains), and a contents list was added at the top. Section numbers are unchanged. |
| [process/roadmap.md](process/roadmap.md) | Open work is first, with new items (delete checkpoints and model calls with a lesson, the forwarded-header bypass, server-side forward-only for the final test). Finished phases are one line each. Every checklist item is kept. |
| [legal/README.md](legal/README.md) | The second, word-for-word copy of the policies was removed. The page text in `frontend/content/legal/` is the only copy, and this file keeps the owner's note and the update checklist. |
| [archive/ui-audit-2026-10-25.md](archive/ui-audit-2026-10-25.md) | Marked as historical. |

## Still open

- **`archive/ui-audit-screenshots/`** is about 30 MB of gitignored PNGs of the old screens. It was not deleted. Remove it when you no longer need the before and after pictures.
- **`architecture/design.md`** is still one 1,700-line file. It was not split, because `CLAUDE.md` and the roadmap link to its section numbers. The contents list at the top is the way in. Splitting it per module under `architecture/design/` is possible if that becomes too heavy.
- **Docs not read line by line:** `lesson-graph.md`, `model-registry.md`, `frontend.md`, `onboarding.md`, `testing.md` and `ci.md`. No stale statements were found in the parts checked.

## Conventions

- New docs go in the folder that matches their job above, and get a row in this index.
- Code comments and other docs link by path (`docs/architecture/design.md`), so moving a file means searching for its old path.
- `CLAUDE.md` is the contributor contract. It points here for the detail.
