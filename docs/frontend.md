# Frontend (Next.js)

Next.js 16 (App Router, Turbopack) with TypeScript, Tailwind v4, and shadcn/ui, managed with **bun**. It is a UI client only: no secrets, no LLM calls, no database access.

## Backend proxy

`app/api/[...path]/route.ts` forwards every `/api/*` request to `${DJANGO_API_ORIGIN}/api/*`. It is a route handler, not a `next.config` rewrite, so it controls the forwarded headers: it passes the visitor's address in `X-Forwarded-For`, which the API's rate limits key on. (A rewrite forwards the Next.js server's own address, which put every visitor in one rate-limit bucket.) Request bodies are buffered, because a streamed body arrives at Django empty. Response bodies are streamed, so Server-Sent Events work.

Django API routes have **no trailing slash** (`/api/lessons`, not `/api/lessons/`). Next.js normalises trailing slashes with a redirect, and Django's `APPEND_SLASH` would redirect back, which would create a loop through the proxy.

Swagger UI and the admin are opened on the Django origin directly (`NEXT_PUBLIC_BACKEND_URL`), because they load Django's static files.

This gives same-origin cookies and needs no CORS configuration. `EventSource` works as-is.

After sign-in, `/auth?next=…` only redirects to a path on this site (`RedirectPolicy.safeNext` in `lib/safe-redirect.ts`). Anything else, such as `//evil.com` or `/\evil.com`, falls back to `/`.

## Pages

| Route | Purpose |
|---|---|
| `/auth` | Login and register |
| `/onboarding` | First-time profile form (skipped once `profile_complete`) |
| `/profile` | Edit profile |
| `/` → `/lessons` | The learner's lessons: topic, stage badge, date, search |
| `/lessons/new` | Topic and optional context ("what do you already know / why are you learning this") |
| `/lessons/[id]` | **Stage-driven view** (below) |

`proxy.ts` (Next 16 renamed `middleware.ts` to `proxy.ts`; it runs on the Node.js runtime) guards `/onboarding`, `/profile`, and `/lessons/*`. Without the `lc_session` marker it redirects to `/auth?next=…`; without `lc_onboarded` it redirects to `/onboarding`. A signed-in visitor to `/auth` is sent home. It checks `lc_session` rather than `lc_access`, because the access cookie expires after 30 minutes while the session (refresh token) lasts 7 days; the API client refreshes silently. The API still enforces everything.

## Lessons screens (Phase 3)

Logic lives in small classes in `lib/` (tested with `bun test`), and the components in `components/lessons/` stay thin:

| Class | What it does |
|---|---|
| `LessonsApi` | The lessons endpoints, typed; extracts the cursor from a list reply's `next` link |
| `RunEventStream` | Follows a run's Server-Sent Events and closes itself after a terminal event (an open `EventSource` would reconnect to a finished run forever) |
| `PipelineModel` | The progress steps for a stage, driven by run events: running or done, retry and fallback notes, warnings |
| `QuizSession` | One question at a time, "I don't know" as an answer, the payload only when complete |
| `StageView` | Which screen a lesson is on, what to say after a score, bands in order |

`useLesson(id)` loads the lesson, follows its active run, refetches when a run segment ends, and polls every 4 s while the lesson is working as a safety net. After Retry the lesson stays `failed` until its first node runs, so an active run always shows the progress screen. Quiz scores and reviews survive a reload (`LessonDetail.results`).

## `/lessons/[id]`: the stage-driven view

The page loads `GET /lessons/{id}`, subscribes to the active run's events, and renders by `stage`:

| stage | Component |
|---|---|
| `preparing_diagnostic`, `generating_material`, `generating_lesson` | `PipelineProgress`: live steps, retries, fallbacks |
| `awaiting_diagnostic` | `QuizRunner kind="diagnostic"` |
| `awaiting_prerequisite` | `QuizRunner kind="prerequisite"`, introduced with "Let's check the foundations first" |
| `awaiting_choice` | `MasteryChoice`: score summary and three cards (Cheat sheet · Revision sheet · Practice sheet) |
| `ready` + route `mastery` | `StudyMaterialView`: tabs for each generated sheet, and "Get another sheet" |
| `ready` + route `lesson`/`prerequisite` | `LessonViewer` |
| `failed` | Error and **Retry** |

When an `awaiting_input` or `done` event arrives, the page refetches the lesson, so the view advances by itself.

### `QuizRunner`

- One question per screen, with a progress bar. Every question has **"I don't know"** as a fifth option. The page says openly that guessing makes the lesson worse, and that "I don't know" is the useful answer when unsure.
- All answers must be given, then submitted in one request. Afterwards, `QuizResultCard` shows the score by band and what happens next: "We'll check a few foundations", "Building your lesson at intermediate level", or "You already know this well".
- A **Review answers** link opens the review endpoint, with correct answers and explanations.

### `StudyMaterialView` (fixed templates, no generated code)

- **Cheat sheet**: dense grid of formula and rule cards (KaTeX), short notes, and a print stylesheet.
- **Revision sheet**: long-form notes with a table of contents and collapsible sections.
- **Practice sheet**: the same `Assessment` UI as page 4, with "reveal solution" per question and grading on submit.
- Exports to PDF with `@react-pdf/renderer` from the structured JSON.

### `LessonViewer`

`LessonViewer` loads `GET /lessons/{id}/document` and mounts `LessonSandbox`. Page navigation (Introduction · Core · Advanced · Test) is part of the generated document itself, and the parent shows only a toolbar: view code, version history, and PDF export of pages 1–3.

## `sandbox/` runtime (shared with backend validation)

The sandbox is its own package at the repo root, so the browser and the backend's `render_check` run **exactly the same** runtime.

```
sandbox/
  src/runtime.tsx       bootstraps React, receives code and data, reports errors and height
  src/scope/            everything generated code may use (below)
  scripts/check.mjs     esbuild parse + Babel AST security/scope scan (called by the backend)
  scripts/render-check.mjs   Playwright headless render + interaction smoke test (called by the backend)
  dist/runtime.js       built bundle; copied to frontend/public/sandbox/ by `npm run build`
```

### Scope available to generated code

| Name | What |
|---|---|
| `useState`, `useEffect`, `useRef`, `useMemo`, `useCallback`, `useReducer` | React hooks |
| `LESSON` | Injected data: `pages`, `final_test` (no answers), `media` (id → signed URL, alt, caption, attribution) |
| `Mafs`, `Coordinates`, `Plot`, `Point`, `Line`, `Vector`, `Circle`, `Polygon`, `Text`, `useMovablePoint` | Interactive math graphs ([mafs](https://mafs.dev)) |
| `motion`, `AnimatePresence` | Animations (motion / framer-motion) |
| `Math`, `BlockMath` | KaTeX formula rendering |
| `CodeBlock` | Syntax-highlighted code |
| `Figure` | `<Figure asset="id" />`: renders a `MediaAsset` with caption and attribution. It is the **only** way to show an image or GIF. |
| `Callout`, `KeyPoints`, `PageFrame` | Consistent building blocks for pages |
| `Assessment` | The page-4 test UI. It collects answers and sends them to the parent with `postMessage` for submission. |
| `render` | Mount call, used only by the assembled document |

Adding a library to the scope is a deliberate change. You update `src/scope`, update the allowed identifiers in `check.mjs`, and document it in the prompts for `interactive.generate` and `page.compile`.

### `LessonSandbox`

```tsx
<iframe sandbox="allow-scripts" srcDoc={harnessHtml} />   // no allow-same-origin → opaque origin
```

- The harness sets a CSP: `default-src 'none'; script-src 'unsafe-eval' <runtime>; img-src <api origin>; style-src 'unsafe-inline'`. This means generated code cannot make network requests even if the static scan missed something. (`unsafe-eval` is needed to run the transformed code.)
- The parent posts `{type: "render", code, data, codeVersion}`. The runtime transforms the TSX with **sucrase** and evaluates it with the scope.
- The runtime posts back `rendered` (with height), `error` (with `phase: transform | runtime`, message, stack, and page), and `test_submit` (answers from `Assessment`). The parent accepts only messages whose `event.source` is this iframe.
- **Runtime errors that slipped past `render_check`** trigger `POST /repair`, at most `max_auto_runtime_repairs` times. After that, the learner sees the error with a **Rebuild** option.
- `test_submit` → `POST /test/submissions`. The result (score, feedback per question, topics to revisit) is shown in a `TestResultPanel` next to the iframe.

## `lib/`

- `api.ts`: `ApiClient` and the shared `apiClient` instance. Same-origin credentials, the CSRF header on unsafe methods, one silent refresh on 401 (shared by concurrent requests, never for the auth endpoints), and typed `ApiError`s.
- `types.ts`: mirrors [api.md](api.md).
- `useRunEvents(runId)`: `EventSource` wrapper. It rebuilds state from `snapshot` and closes on terminal events.
