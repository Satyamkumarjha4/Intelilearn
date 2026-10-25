# Frontend (Next.js)

Next.js 16 (App Router, Turbopack) with TypeScript, Tailwind v4, and shadcn/ui, managed with **bun**. It is a UI client only: no secrets, no LLM calls, no database access.

## Backend proxy

`app/api/[...path]/route.ts` forwards every `/api/*` request to `${DJANGO_API_ORIGIN}/api/*`. It is a route handler, not a `next.config` rewrite, so it controls the forwarded headers: it passes the visitor's address in `X-Forwarded-For`, which the API's rate limits key on. (A rewrite forwards the Next.js server's own address, which put every visitor in one rate-limit bucket.) Request bodies are buffered, because a streamed body arrives at Django empty. Response bodies are streamed, so Server-Sent Events work.

Django API routes have **no trailing slash** (`/api/lessons`, not `/api/lessons/`). Next.js normalises trailing slashes with a redirect, and Django's `APPEND_SLASH` would redirect back, which would create a loop through the proxy.

Swagger UI and the admin are served by Django on its own origin (`NEXT_PUBLIC_BACKEND_URL`), because they load Django's static files. No public page links to them.

This gives same-origin cookies and needs no CORS configuration. `EventSource` works as-is.

After sign-in, `/auth?next=…` only redirects to a path on this site (`RedirectPolicy.safeNext` in `lib/safe-redirect.ts`). Anything else, such as `//evil.com` or `/\evil.com`, falls back to `/`.

## Pages

| Route | Purpose |
|---|---|
| `/` | The public landing page, for signed-out visitors only (see "The landing page" below). A signed-in visitor is redirected to `/lessons`, or to `/onboarding` if they have not finished it |
| `/auth` | Login and register |
| `/onboarding` | First-time profile form (skipped once `profile_complete`) |
| `/profile` | Edit profile |
| `/lessons` | "My lessons": a "Continue where you left off" card, filter chips (All, Needs you, Building, Ready, Couldn't finish), search, and lesson cards (3 / 2 / 1 columns) whose pill says the next action (`LessonStatus`) |
| `/lessons/new` | "What do you want to learn?": a big topic input with an "n / 200" counter, example chips, an optional note, and the three steps ahead (`NewLesson` holds the rules and the plain-words error messages) |
| `/lessons/[id]` | **Stage-driven view** (below) |

`proxy.ts` (Next 16 renamed `middleware.ts` to `proxy.ts`; it runs on the Node.js runtime) is a thin hook: it reads the `lc_session`, `lc_onboarded` and `lc_setting_up` cookies and asks `RouteGuard.redirectFor` (`lib/route-guard.ts`). `/` and `/auth` are for signed-out visitors: with `lc_session` they go to `?next=` when it is a safe path on this site (`RedirectPolicy.safeNext`), else `/lessons`, or through `/onboarding` without `lc_onboarded`. `/onboarding`, `/profile` and `/lessons/*` need the marker: without it they redirect to `/auth?next=…`, and without `lc_onboarded` to `/onboarding?next=…`, so the page they wanted is kept. An onboarded visitor has nothing to set up and is sent on from `/onboarding`, except in the last step: the profile is saved at step 4, which makes them onboarded, so the page sets the `lc_setting_up` cookie (`SetupMarker`) then and clears it when the setup ends, and a refresh on step 5 stays there with the landing page's topic still offered. The API still authorises every request.

The markers are httpOnly, so the page cannot read them. `GET /api/session` (`app/api/session/route.ts`, `SessionProbe`) says whether `lc_session` is there; `AuthProvider` asks it before `/auth/me`, so a signed-out visitor's console stays free of 401s. Loading and error states: `app/loading.tsx`, `app/lessons/loading.tsx`, `app/lessons/[id]/loading.tsx`, `app/error.tsx` and `app/global-error.tsx` (the root layout itself failed), and the console's own `loading.tsx` and `error.tsx` (the sidebar stays).

## The landing page

`/` is built from `docs/design/mockups/socra-mockup.html`, screen 11, with the root header hidden (`SiteHeader` returns nothing on `/`) in favour of its own public header: logo, the anchors `#how` and `#paths`, "Sign in" and "Get started". `app/page.tsx` is a server component, so the whole page is in the HTML the server sends. The client islands are the try-it card, the walkthrough, the carousel, the call to action's form (it needs `sessionStorage` and the router) and the `Reveal` wrapper. Words live in `lib/landing-content.ts`; components in `components/landing/` are thin and the rules are classes in `lib/`:

| Class | What it does |
|---|---|
| `RouteGuard` | Where a visitor may be (above) |
| `DemoQuestions` / `DemoQuestionFetcher` | The hero's question: `parse` accepts only a question the card can show (three options, an answer among them, band 1–5, both outcomes), `label` is "<band name> · <subject> · <level label>", `fallback` is the built-in maths question (id 0), which is none of the seeded ones. The fetcher asks `/api/landing/demo-question` with `cache: no-store` and a 1.5 s limit, and gives `null` for anything that goes wrong |
| `HeroDemo` | What the try-it card says for a question: its right option is right; a wrong answer and "I don't know" get the same encouraging copy and the question's wrong outcome |
| `Autoplay` | The carousel's timer: every 6 s, looping; hover (mouse only), keyboard focus, touch (resumes 4 s after the finger lifts) and being less than 30% on screen pause it, remembering the time that was left; choosing a slide restarts a full interval; off for reduced motion. `useAutoplay` wires it to the page |
| `Walkthrough` | The "How it works" steps: autoplay every `STEP_MS` (5 s) once the section is in view, wrapping; choosing a step (click or arrow key) stops it for good |
| `ScorePaths` | Which path a quick-check score leads to (0–2 foundations, 3–9 lesson, 10 study sheet) and the ten score dots; the carousel's example learners are tested against it |
| `SlideCycle` | Carousel arithmetic: wrapping previous/next, the slide an arrow key leads to, and the slide a scroll position settled on (a swipe). The arrow keys act on the tabs and the track only, stop the track scrolling itself, and move focus with the tab |
| `PendingTopic` | The topic typed into the call to action, kept in `sessionStorage` under `socra.pendingTopic` through sign-up. It never throws: no storage, or a blank box, must not stop sign-up. Nothing reads it back yet |
| `RevealPolicy` | What waits to pop in on scroll (below 92% of the screen) and the 80 ms stagger |

- **The hero question.** `app/page.tsx` asks Django for a random question on the server (`cache: "no-store"`, forwarding the visitor's address so the API's limit is theirs), so every load shows a different one and it is in the HTML: no flash. If the API fails or times out, the built-in question is shown. While the result card is on screen the next question is already being fetched (excluding the current one), so "Try again" flips straight to it with the deck's fly-and-rise motion; if that fetch fails the built-in question is used, unless it is the one just seen.
- **"How it works" layout.** The stage stretches to the height of the step list (no `min-height`); inside it the caption chip is at the top left and the preview card directly under it, top-aligned, at most 520px wide; 24px between the intro and the list.
- **Carousel autoplay.** The active tab shows a bar filling along its bottom edge over the interval, paused with the timer and restarted on every change. Keyboard focus pauses it, but the focus a mouse click leaves behind does not (the pointer being over the carousel already does, and otherwise autoplay would stay off after a click). The track is `aria-live="off"` while it plays by itself and `"polite"` for a change the visitor made. Reduced motion: no autoplay and no bar.
- **Reuse.** The try-it card flies and rises with `DeckMotion` (`lib/deck-motion.ts`), the same constants the quick check's `FlashcardDeck` uses. The previews are built from `SegmentBar`, `LevelMeter` (also used by `StartingPointCard`), `Badge`, `Card` and the lesson book's flap colours, extracted so the landing page and the app draw the same thing.
- **Motion.** `app/landing.css` holds the keyframes. Components mark what moves with `data-anim` and a `--d` delay, and a container plays them with `data-play="true"`. Scroll reveal is set by the browser only (`useReveal` writes `data-reveal` on the element), so nothing is hidden on the server and nothing re-renders or shifts. A visitor with `prefers-reduced-motion` gets no autoplay, no reveal and no flying cards, and on paper (`@media print`) nothing waits to pop in. Without script the page is whole. Anchors scroll smoothly (`data-scroll-behavior="smooth"` on `<html>`, as Next asks).
- **Known gap.** The footer links to `/privacy` and `/terms`, which are not written yet; "Contact" is plain text until there is an address.
- **Contrast.** White text on `primary` is 3.04:1, below 4.5:1 for small text (the header's "Get started", the hero's, and the call to action's second line). It is the palette's value, so it is a design decision rather than a landing-page fix. A signed-in visitor to `/auth` is sent home. It checks `lc_session` rather than `lc_access`, because the access cookie expires after 30 minutes while the session (refresh token) lasts 7 days; the API client refreshes silently. The API still enforces everything.

## Lessons screens (Phase 3)

Logic lives in small classes in `lib/` (tested with `bun test`), and the components in `components/lessons/` stay thin:

| Class | What it does |
|---|---|
| `LessonsApi` | The lessons endpoints, typed; extracts the cursor from a list reply's `next` link |
| `ConsoleApi` (`lib/console-api.ts`) | The staff-only console endpoints ([api.md](api.md#console-staff-only)), typed with the `Console*` types of `lib/types.ts`, plus the link that downloads the usage CSV. The console answers a stranger with a 404, which also hides an expired access cookie, so a 404 renews the session and is tried once more (at most one renewal a minute). `User.is_staff` (from `/auth/me`) says whether to offer the console at all. The Lesson runs screen is the first console screen (below) |
| `ConsoleGate` | Who may see the console: `decide` turns the session into checking, signed-out (sent to `/auth?next=` with the page and filters kept), denied (the ordinary not-found page, so the area does not announce itself) or allowed; `offeredTo` says whether the account menu shows the Console link (staff only) |
| `ConsoleQueries`, `ConsoleQueryClient`, `ConsoleErrors` | The console's TanStack Query setup (the only use of it): query keys under `"console"` that carry the filters, the overview polled every 60 s, the sidebar's failed-runs badge, one client per visit that refetches on focus and does not retry a 400, 401, 403 or 404 |
| `ConsoleFormat`, `ConsoleUrl`, `ConsoleNav` | How numbers are written (money, call times, percent changes, axis labels), the address state of the Overview (`?range=`) and Usage (`?range=&start=&end=&provider=&model=&node=&outcome=`) pages with forgiving reads, and the sidebar entries |
| `ProviderSeries`, `SpendChart`, `LatencyChart`, `OutcomeChart`, `FunnelChart`, `SlowestSteps`, `StepTable`, `OverviewKpis`, `UsageKpis` (`lib/console-charts.ts`) | Everything the console draws, worked out from the API replies: provider colours (Groq, Google, OpenAI, else Other: fixed, never by rank), stacked rows, tiles, sparklines, tooltip contents, table forms, bar geometry. The status colours are used only by `OutcomeChart` |
| `UsageFilterOptions` | The usage drop-downs' choices (providers by key, a model once, only the provider's), and the rule that changing the provider clears a model it does not serve |
| `LearnerText`, `LearnerStats`, `PeopleUrl`, `AdminLinks` (`lib/console-people.ts`) | The Learners page's words and numbers: studies ("School · Class 10"; a bare number is a class at school and a year at college), goal, language in its own script, last active, onboarding; the four tiles (the counts are the API's summary over everyone; "new this week" and "most common" come from the newest 100 and say so when that is only a sample); the `?q=` search; and the Django admin link, built from `NEXT_PUBLIC_DJANGO_ADMIN_URL` (an `http(s)` address, the admin's own or just the backend's origin) |
| `AuditText`, `AuditAreas`, `AuditDiff` (`lib/console-audit.ts`) | The Change log: each change as a sentence with its targets in code, the actor, the areas (routing, models, settings, runs) the filter offers, and the before and after of each changed field in words (on and off, a model chain as "a → b") |
| `PeopleQueries` (`lib/console-people-queries.ts`) | The paged queries of both pages (learners by search, the 100-learner sample, the change log), with the next page's cursor taken from the reply |
| `RunFilters`, `RunText` | The Lesson runs page's address (`?status=&job=&q=&run=`, defaults left out, unknown values and any `run` that is not a whole UUID dropped) and its words: durations, costs (three places under a cent), status pills (a paused run reads "Waiting for learner"), job and stage names, "12 min ago" with the exact time for the title. The Running tab asks for `queued` and `running`; Finished asks for `succeeded` only. The search box is sent as `q` (topic, learner name or email); a whole run id typed or pasted into it opens that run instead, since the API does not search ids |
| `RunTimeline` | Lays timeline steps out: phases in the order Diagnose, Author, Build, After, Other (an unknown phase goes to Other), one lane per step, `left` and `width` in percent of the run's length (the longer of the last step's end and the run's own time), at least 1.5% wide and never past the right edge, a waiting step drawn to the end of the run, no bar for a step with no kept times. Also the hover text and the lane's spoken sentence. The API gives a step a `state` but no attempt count, so the hover text says "Ran again after a failed check" for a retried step instead of a number |
| `RunFollower`, `RunActions` | Keeps the open run current (events or a poll, see [design.md](design.md#411-frontend-frontendlib)) and runs Retry and Stop, turning each `409` code into a sentence for a toast |
| `RunEventStream` | Follows a run's Server-Sent Events and closes itself after a terminal event (an open `EventSource` would reconnect to a finished run forever) |
| `PipelineModel` | The building screen's steps for a stage, driven by run events: friendly names, running or done, a percentage and headline, how long each step took (measured here), sub-lines ("2 of 3 pages written"), one calm "recovered" flag for retries and fallbacks (never a model name), warnings |
| `Journey` | The journey stepper (Diagnose → Your level → Learn → Test → Revisit, or the mastery route) and the tag next to the title, from the lesson's stage, route, assessment and test status; a failed lesson keeps the step it failed on |
| `LessonStatus` | The pill of a lesson in the list: a ready lesson says "Ready" until all three pages have been read in this browser (`ReadPages`), then "Take the test", then "Test done · 70%" |
| `LessonTabs` | The tabs of a ready lesson (`?tab=lesson\|test\|answers`), the Test tab's badge, and which tab an address selects |
| `SheetCatalog`, `SheetTabs`, `MasteryBanner` | The three study sheets described once (title, one line, three bullets, reading time, "Make my revision sheet" / "Add practice sheet" labels), the tab row of a mastery lesson (sheets it has first in catalogue order, then dashed ones to add, one possibly "building"; which tab is open), and the choice screen's celebration text |
| `CheatGroups` | How one cheat-sheet section is laid out: formulas, key terms, plain points (nothing dropped, order kept) |
| `StartingPoint` | The "Your starting point" card: level meter (1–5), a dot per quick-check question by band (right, not yet, I don't know), confidence |
| `PlainWarning`, `PlainError` | The builder's notes and a failed lesson's reason in words a learner can read; nothing technical leaks |
| `DeckSession`, `DeckStore` | The flashcard deck behind the quick check and the final test: forward only, an answer locks when the learner continues, the payload only once finished; kept in `sessionStorage` so a refresh resumes on the same card |
| `StageView` | Which screen a lesson is on, what to say after a score, bands in order |
| `PracticeSession` | A practice sheet attempt: answers, revealed solutions, marks from the server (nothing is stored server-side) |
| `PlainText` | Markdown and LaTeX reduced to plain text for the PDF |
| `StudyPdf` | A study sheet as a PDF (`@react-pdf/renderer`), built from the structured JSON and loaded only when the learner downloads |

`useLesson(id)` loads the lesson, follows its active run, refetches when a run segment ends, and polls every 4 s while the lesson is working as a safety net. After Retry the lesson stays `failed` until its first node runs, so an active run always shows the progress screen. Quiz scores and reviews survive a reload (`LessonDetail.results`).

## `/lessons/[id]`: the stage-driven view

Every state has the same header (`LessonHeader`): breadcrumb (My lessons / topic), title, a small tag (level, else route), and the `JourneyStepper` (on a phone only the current step keeps its label). Once the lesson is `ready` the tabs of `LessonTabs` sit under the stepper (`LessonTabBar`, the open tab in `?tab=`): **Lesson**, **Test** (badge "1 attempt", then "70% · final") and **Quick check answers**, or **Study sheets** and **Quick check answers** for a mastery lesson. The Test tab is the `TestRunner` deck, or the result once the test was submitted.

The page loads `GET /lessons/{id}`, subscribes to the active run's events, and renders by `stage`:

| stage | Component |
|---|---|
| `preparing_diagnostic`, `generating_material`, `generating_lesson` | The building screen: `PipelineProgress` (eyebrow, headline, percent and bar, timeline with per-step time, a calm note when a step needed a second try, collapsed "Small notes", **Stop building** behind a `ConfirmDialog`) beside `StartingPointCard` (once the assessment exists; stacked on a phone). `loading.tsx` shows its skeleton. |

Layout of the building screen: two columns, `minmax(0,1.15fr)` / `minmax(0,1fr)`, aligned to the top; the progress card is sticky (top 1rem plus the safe area) so it stays in view while the taller starting-point card scrolls, and below 900px they stack, progress first. The timeline always lists every step of the phase (while a quick check is prepared: getting to know you, writing the questions, checking them, getting them ready; "foundations check" in the words when the route is prerequisite). While no step is done yet there is no "0%": an indeterminate bar and "Usually takes under a minute" show, and the percentage appears when the first step finishes. The card's footer has "Started X ago" (from the run's `started_at` in the stream's first event) and **Stop building** (its dialog belongs to the learner's action, not to the run: it stays open if the run ends or flickers, and says so, `StopControl`). After a Retry the model reads "Picking up where it stopped" until the lesson's real stage is known. In the starting-point card a diagnostic is not an exam, so there is no red: right is a green dot, not yet an amber ring, "I don't know" a dashed empty dot; topic chips are shown in sentence case (`Chips`), six at a time with a "+N more" toggle that opens the rest in place (and "Show fewer").
| `awaiting_diagnostic` | `QuickCheck kind="diagnostic"` |
| `awaiting_prerequisite` | `QuickCheck kind="prerequisite"` ("Quick check · the basics first") |
| `awaiting_choice` | `MasteryChoice`: a marigold banner with a trophy ("10 out of 10. You already know this!"), "What would help you most?" and three pressable radio cards (Cheat · Revision · Practice: icon, one line, three bullets, reading time; the picked one is primary-soft with a primary border and shadow, revision is picked to begin with), and a button that follows the pick ("Make my revision sheet") → `POST /choice`, then the building screen. The score is not repeated as a result card; **Review answers** stays below. |
| `ready` + route `mastery` | Tab **Study sheets**: `StudyMaterialView` (see below) |
| `ready` + route `lesson`/`prerequisite` | Tab **Lesson**: `LessonViewer` |
| `failed` | `FailedCard`: "We couldn't finish building this", the reason in plain words, **Retry** and Back to my lessons |

A ready lesson always shows its tabs, even while a run (a repair, a grading, another sheet) is active. `app/not-found.tsx` and `app/error.tsx` use the same `StatusCard` as the failed card. Confirmations use the `Dialog` primitive (`components/ui/dialog.tsx`) through `ConfirmDialog`, never `window.confirm`.

When an `awaiting_input` or `done` event arrives, the page refetches the lesson, so the view advances by itself.

### `FlashcardDeck`, `QuickCheck` and `TestRunner`

`FlashcardDeck` shows one card at a time over two ghost cards that thin out as fewer questions remain, a segmented progress bar and "n / total". **There is no way back**: Continue is disabled until the card is answered, a lock hint says so, and the answer locks when the learner continues. The answered card flies off to the left and the next rises from the stack (~450 ms; instantly for `prefers-reduced-motion`). Keys: 1–4 / A–D pick options (D is "I don't know" in the quick check), Enter continues (not in a textarea). Answers are kept in memory and in `sessionStorage` (`deck:<lesson>:<kind>`), sent in one request at the end, and forgotten after a successful send.

- **`QuickCheck`** (diagnostic and prerequisite): a difficulty bar and band name, the question, four options keyed 1–4 and a dashed "I don't know this yet (D)". After the last card a "Quick check done!" card flips in ("Working out your starting point…") while the flow resumes; a failed send keeps the answers and offers "Send my answers". `409 already_attempted` hands over to the read-only answers.
- **`TestRunner`** (Test tab, `GET /lessons/{id}/test`): "Final test · Show what you learned" with a "One attempt" chip; multiple choice (A–D), number (with unit), short answer, written answer and code (monospace, starter code prefilled; unchanged counts as unanswered). The last button is marigold "Finish and submit" and opens "Submit your test?" (Not yet / Submit for good); then "Marking your test" while the `grade_test` run is followed, then the result (`TestResults`, polling while marking). A test that already has a submission never shows the deck, and `409 already_submitted` goes to the result.
- A **Review answers** link on the quick check result opens the review endpoint, with correct answers and explanations.

### The read-only views

- **Test results** (`TestResults`, Test tab after submitting; `TestReport` in `lib/test-report.ts`): a lock note ("Your test is final… Submitted <date>"); a hero card with a score ring, a headline chosen by score band and chips (correct, partly right, missed, written answers graded by AI); "Worth another look", one card per topic to revisit with a marigold **Make a lesson on this** (`POST /lessons` with "Follow-up to my <lesson> test", then the new lesson opens; a 429 gets a friendly "wait a little while"); "Question by question", an accordion with a status icon, marks and a type tag, and when open the learner's answer (from `submission.answers`), the correct answer and the feedback. While the written answers are marked it shows "Marking your test" (and asks again every few seconds); if marking failed it says that is on us and offers **Try marking again** (`regrade`). It never offers another attempt. Actions: Review the lesson, Back to my lessons.
- **Quick check answers** (`QuickCheckAnswers`, `AnswersView`; tab "Quick check answers"): "Quick check · taken <date>" (from the review's `submitted_at`), a Read-only chip, the score ("7 / 10") and the dots per band, a toggle to the foundations check when there is one, and every question in one list: difficulty bar and band, a verdict chip (Correct, Not quite, You said "I don't know"), all options with the right one marked and the learner's own wrong pick, and the explanation. No inputs anywhere.

### `StudyMaterialView` (fixed templates, no generated code)

Sheets render Markdown with KaTeX (`components/markdown.tsx`: `react-markdown`, `remark-math`, `rehype-katex`). A print stylesheet in `globals.css` hides the site chrome and controls; the printer button uses it and **PDF** uses `StudyPdf`.

- **Tab row** (`SheetTabRow`): one chunky tab per sheet the lesson has (the open one primary), a dashed "+ Add <kind> sheet" tab for each it lacks, and **PDF** (plus a print icon) on the right. Asking for a sheet (`POST /materials`) turns its tab into a spinner tab and shows the building screen (`PipelineProgress`, "Writing your revision sheet") inline; when the run ends the sheet loads and opens. The other dashed tabs wait while a sheet is being written (one at a time). The lesson only says that a run is active, not for which sheet, so the page remembers the one it asked for; after a reload mid-run it shows a general "Writing another study sheet" card. A run that ends without the sheet shows "We couldn't write your … this time" with **Try again**. A sheet stays mounted once opened, so a practice sheet keeps its answers while another is open.
- **Cheat sheet** (`CheatSheetView`): a two-column grid of bordered boxes, one per section, with an uppercase primary-text heading; formulas in a muted box (KaTeX, variables, "Use when"), key terms as a definition list, rules and facts as points; the sheet's summary closes it as the full-width insight-soft **Remember** box.
- **Revision sheet** (`RevisionSheetView`): a row of links to the subtopics, then a box per subtopic (summary, key points, worked examples in a muted box, common mistakes each with a coral "!"), and the final tips as **Remember**.
- **Practice sheet** (`PracticeSheetView`): the same question cards as the final test (lettered options, number and text inputs), **Reveal solution** per question, **Check my answers** for the questions that can be marked (the right option turns green and a wrong pick coral once its solution is shown), and the solution in a primary-soft box.
- Shared pieces are in `sheet-parts.tsx` (`SheetHeading`, `SheetBox`, `RememberBox`, `MistakeList`, `MutedBox`).

### `LessonViewer`

`LessonViewer` loads `GET /lessons/{id}/document` and shows the lesson as a **notebook** (`LessonBook`, state in `lib/lesson-book.ts`): the sandboxed iframe sits on paper (`--paper`) with spiral binding, a faint margin line and the edge of a stack of pages. The document shows **one page at a time and has no navigation of its own**: the runtime's `LessonShell` (in `sandbox/src/scope/shell.tsx`, so older lessons work without regenerating) draws only the open page, and the app turns the pages.

- **Toolbar** above the book: eyebrow ("Page 2 of 3 · Core"), the page title, **PDF** (prints the three pages from the structured page content with `LessonPdf`; the test is never included), and a "⋯" menu: **Version history** (earlier versions the repairs and restores kept, each with **Restore**), **View code**, and **Reload this lesson** (asks first through `ConfirmDialog`, then reloads the document and starts a fresh iframe; it does not ask for a repair, the repair limit is the server's).
- **Index flaps** (Introduction, Core, Advanced) on the right edge, tinted primary, marigold and insight. The open one takes the paper colour and joins the page; the others tuck behind it; read pages show a tick. Below 900px they become tabs along the top edge.
- **Footer**: ← Previous page, "Page n of 3", Next page →. On the last page the button is marigold "Go to the test →" (the Test tab), or "See your test results →" once the test was submitted. A new page slides in from the right unless the learner prefers less motion. ← and → turn the page when focus is not in the iframe, a field, a dialog or a menu.
- **Read ticks** are kept in `localStorage` per lesson (`ReadPages`); without storage the book works and shows none after a reload.

A crash the runtime reports shows an alert under the toolbar; while a repair runs a friendly overlay covers the page ("Fixing a glitch on this page…"), and when it finishes the document is reloaded and the new `code_version` is rendered in the same iframe. When the repair fails or the limit is reached the alert says plainly that something did not work (never the page's own error text) and points to Reload and Versions.

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
| `Assessment` | The test UI of lessons made before the test became its own screen (their code still has a `test` page, see `has_embedded_test`). It collects answers and sends them to the parent with `postMessage`. New lessons do not use it. |
| `render` | Mount call, used only by the assembled document |

Adding a library to the scope is a deliberate change. You update `src/scope`, update the allowed identifiers in `check.mjs`, and document it in the prompts for `interactive.generate` and `page.compile`.

### `LessonSandbox`

```tsx
<iframe sandbox="allow-scripts" srcDoc={harnessHtml} />   // no allow-same-origin → opaque origin
```

- The harness sets a CSP: `default-src 'none'; script-src 'unsafe-eval' <runtime>; img-src <api origin>; style-src 'unsafe-inline'`. This means generated code cannot make network requests even if the static scan missed something. (`unsafe-eval` is needed to run the transformed code.)
- The parent posts `{type: "render", code, data, codeVersion, theme}` (media URLs made absolute, because the iframe's origin is opaque) and `{type: "theme", theme}` when the theme changes, which does not restart the lesson. The runtime transforms the TSX with **sucrase** and evaluates it with the scope.
- The runtime posts back `rendered` (with height), `error` (with `phase: transform | runtime`, message, stack, and page), `pages` (`{count, titles}`, when the document starts) and `page_changed` (`{index}`). The parent accepts only messages whose `event.source` is this iframe. The parent sends `render` (with `hide: ["test"]` for a lesson whose `has_embedded_test` is true, so its old test page is left out), `theme` and `set_page {index}`; a freshly started document opens on its first page, so the parent answers `pages` with `set_page` to put the learner back where they were. `test_submit` (from an old lesson's `Assessment`) is still parsed but no longer shown, because that page is hidden.
- **Runtime errors that slipped past `render_check`** trigger `POST /repair`, **once per `code_version`** (`RepairGate`: one crash raises several errors, and one repair covers them; an error from a version the page has moved past is ignored). The server enforces `max_auto_runtime_repairs`: on `repair_limit_reached` the gate stops for good and the learner is told plainly, with **Reload this lesson** and **Version history**. A `stale_code_version` just reloads the document.
- The test is not part of the book: it is taken once, on its own screen (the Test tab), and the server refuses a second submission with `409 already_submitted`.

## Sign in and create account (`/auth`)

A split card: a primary-coloured brand panel (the logo with a marigold mark, a headline per mode, the three steps, tilted translucent cards; on a phone only the logo and headline) beside the form. Segmented tabs switch between "Sign in" and "Create account" without a reload: the address (`?mode=register`, `?next=`) and the tab title follow. The rules and words are in `AuthRules` (`lib/auth-form.ts`, bun-tested): client checks before sending (email shape, a name, the two password rules the server enforces), a live password checklist (the common-password rule is only the server's), friendly messages for a wrong password, the throttle (using `Retry-After`) and a network failure, and where to go afterwards. Server messages stay authoritative and still map onto fields. The password field has a Show/Hide button; there is no "forgot password" because the feature does not exist yet.

`?next=` survives onboarding: an incomplete profile goes to `/onboarding?next=<next>`, which finishes to `RedirectPolicy.safeNext(next, "/lessons")`. A signed-in visitor opening `/auth` is sent on by the route guard, and signing out goes to `/`. `sessionStorage` `socra.pendingTopic` is left alone for onboarding.

`/privacy`, `/terms` and `/contact` use the landing page's public header and footer (Privacy · Terms · Contact). The words are not in components: `frontend/content/legal/privacy.md` and `terms.md` are the copy of `docs/legal/socra-legal-copy.md` verbatim, and `content/legal/contact.ts` holds the Contact page's words (the only email address in the product, the five topics with their subject lines, the grievance officer). `LegalDocument` (`lib/legal-document.ts`) reads a markdown file into its "last updated" date, introduction, numbered sections (with anchors) and tables; `LegalPage` lays them out at about 70 characters a line, with a sticky "On this page" list beside the text on a wide screen and folded at the top on a narrow one, and a cookie table that scrolls inside its own box. Editing the copy means editing those files. The Contact page offers "Copy email" (`Clipboard`: the API, then a hidden-box fallback, then the text selected for the learner to copy) and "Open in mail app", and per topic a mail link plus the subject line as text to copy (`Mailto`). The lesson viewer's "⋯" menu has "Report a problem" (the lesson address and page in the message), and `/profile` ends with "Delete my account" (by email for now).

**Consent at sign-up:** Create account has a required checkbox ("I'm 18 or older, or my parent or guardian has agreed to Socra's Terms of Use and Privacy Policy"). The API refuses a register without `accept_terms` (`400`, "Please confirm to continue.") and keeps `terms_accepted_at` and `terms_version` ("2026-10-25", `User.TERMS_VERSION`) on the user; change the version whenever the Terms or Privacy Policy change in a way that matters.

## Setup (`/onboarding`) and profile (`/profile`)

A focused five-step page (no app navigation): the logo mark, a segmented progress bar and "n / 5", Back (allowed here, unlike in a quiz) and Continue, with each step sliding in from the side the learner came from (no slide for reduced motion). The state is `OnboardingFlow` (`lib/onboarding-flow.ts`, bun-tested): what each step needs, the follow-up questions that fill `grade_or_year` and `field_of_study`, and the profile to save. `OnboardingStore` keeps the place and answers in `sessionStorage` (`socra.onboarding`) so a refresh resumes.

1. **Studies**: School, College, Postgraduate, Working, Self-learner, then a follow-up (class chips; year chips and "What are you studying?"; "What field do you work in?"; an optional focus).
2. **How you learn** (Seeing, Reading, Doing, A mix) · 3. **Goal** · 4. **Language** (each in its own script, English preselected) with optional notes. **Continue on step 4 saves the profile** (`PUT /profile`), so `lc_onboarded` is set before step 5.
5. **Where to start**: chips of what the suggestions are based on (with "Change", back to step 1), four topic cards from `POST /onboarding/topic-suggestions` (`TopicSuggestions`, read defensively; "Show me others" when `has_more`), or "Or type your own topic" (prefilled from `socra.pendingTopic`, which is then cleared). A card and the typed topic are one choice (`TopicPick`). "Start my quick check" creates the lesson; "I'll do this later" goes to `?next` or `/lessons`.

The tiles are friendly copy keyed by the values `GET /profile/options` returns (`OnboardingChoices` merges them: a value only the API knows is shown under its API label). A finished profile visiting `/onboarding` is sent to `/lessons` by the route guard. `/profile` is the same tiles and follow-up questions on one page (`ProfileEditor`) plus the name and the read-only email.

**Topic suggestions contract:** `POST /onboarding/topic-suggestions` with the answers of steps 1 to 4 (`education_level`, `goal`, `preferred_language`, `grade_or_year`, `field_of_study`) and `page` (from 0, wrapping) answers `{topics: [{title, title_en, subject, reason}], has_more}`; the cards show `title` (in the learner's language). It follows the backend module `backend/onboarding`, which is still being built: until the endpoint answers, step 5 says it couldn't find ideas and the learner types a topic.

## Brand

The product is **Socra**. `components/brand/logo.tsx` draws the logo: a teal rounded square with a pressable shadow and the lucide `MessageCircleQuestion` icon (a tutor that asks before it teaches), plus the name in the heading font. `variant="full" | "mark"`, `size="sm" | "md" | "lg"`. The site header and the landing page use it; auth and onboarding should too. `app/icon.svg` and `app/apple-icon.png` are the same mark. The page title template is "%s · Socra".

## Design system

All colour, type and radius come from tokens in `frontend/app/globals.css` (Tailwind v4, CSS-first, no `tailwind.config`). Components use token utilities (`bg-primary-soft`, `text-marigold-text`, `shadow-card`), never raw palette classes such as `emerald-600`.

- **Roles.** `primary` (Lagoon teal) is the main action, progress and the current step. `marigold` is the warm partner: secondary calls to action, "waiting for you" states, gaps to learn. `insight` (grape violet) marks AI moments: the learner assessment, the level meter, key-idea callouts and AI feedback. `success` is green and `destructive` is coral.
- **Token family.** Each brand colour has a solid value, a `-soft` tint for backgrounds and a `-text` shade that reads on surfaces (`primary` and `marigold` also have `-deep`, the colour of the pressable button's shadow). The shadcn names (`background`, `card`, `muted`, `border`, `ring`, …) keep working. Light neutrals are teal-tinted (hue 190); dark neutrals are grape-tinted (hue 295). Every token is registered under `@theme inline`, so the Tailwind utility exists.
- **Shape.** `--radius: 1rem`, so inputs and buttons land near 13px (`md`), cards at 22px (`xl`, written `rounded-[22px]`). Cards use a 1.5px border and `shadow-card` instead of a ring.
- **Type.** Fredoka 500/600 for `h1`–`h3` (`--font-heading`, weight 600, line height 1.2, balanced), Nunito 400/600/700/800 for body and controls (`--font-sans`; buttons are 800, labels and badges 700), JetBrains Mono for code (`--font-mono`). All three load through `next/font/google` in the root layout, so nothing is fetched from Google at run time.
- **Buttons.** `default` (teal) and `marigold` are pressable: a flat 4px shadow in the `-deep` colour that shrinks while the button moves down 3px. `outline` is the same shape on a card surface with a 2px border. Disabled solid buttons turn into a muted surface with no press effect. The press and its transition are off under `prefers-reduced-motion`. `secondary`, `ghost`, `destructive` and `link` stay flat.
- **Badges.** `success`, `marigold`, `insight`, `primary` and `destructive-soft` use the `-soft` and `-text` pair; `default`, `secondary`, `outline` and `destructive` are unchanged.
- **Theme.** `next-themes` toggles the `dark` class; the header's `ThemeToggle` offers Light, Dark and System (the default).
- **The lesson iframe has its own copy.** The page only sends `light` or `dark`, so the palette lives in `sandbox/src/harness.html` as well (run `docker compose run --rm sandbox-build` after editing it). `lib/theme-tokens.test.ts` fails if a colour in the harness differs from `globals.css`, if a brand token is missing, or if a component or sandbox scope file uses a raw palette colour. The harness CSP allows no network fonts, so inside the iframe text uses a rounded system stack (`ui-rounded, "Nunito", system-ui`). Self-hosting Nunito and Fredoka for the iframe would need `font-src` to allow the app origin, or fonts embedded as `data:` URIs.

## `lib/`

- `api.ts`: `ApiClient` and the shared `apiClient` instance. Same-origin credentials, the CSRF header on unsafe methods, one silent refresh on 401 (shared by concurrent requests, never for the auth endpoints), and typed `ApiError`s.
- `types.ts`: mirrors [api.md](api.md).
- `theme-tokens.test.ts`: keeps the app palette and the sandbox harness palette identical (see Design system).
- `useRunEvents(runId)`: `EventSource` wrapper. It rebuilds state from `snapshot` and closes on terminal events.

## Console: shell, Overview and Usage & cost (`/console`)

Built from the Overview and "Usage & cost" pages of [socra-admin-mockup.html](design/mockups/socra-admin-mockup.html), denser than the learner app (14px body, compact tables, mono numbers). `app/console/(shell)/layout.tsx` mounts `ConsoleShell`; the pages only mount their view inside the `Suspense` that `useSearchParams` needs.

- **Access:** `proxy.ts` sends a signed-out visitor to `/auth?next=/console...`. `ConsoleShell` then reads `/auth/me`: a learner (`is_staff` false) gets Next's `notFound()`, and no console request is made; any console endpoint answering 404 does the same (`useConsoleQuery`). The account menu shows a Console link to staff only. The learner app's header is not shown under `/console`.
- **Shell:** `ConsoleSidebar` (Logo and "Console", Monitor / Configure / People, a red badge on Lesson runs with the failed runs of the last 24 hours, the user, the theme toggle and "Back to Socra"). Below 900px it becomes a horizontally scrolling top bar. A "Skip to content" link comes first.
- **Shared components** (`components/console/`): `PageHeader`, `KpiTile` (value, delta chip, sparkline or meter), `StatusPill`, `HealthPill`, `DataTable` (sortable headers with `aria-sort`, sticky header, sideways scroll), `FilterBar` with `FilterSelect` and `FilterDate`, `RangeToggle`, `ChartCard` (title, subtitle, legend, "Show as table"), `EmptyState`, `ErrorState`, skeletons, `HoverTip` (hover and focus box for marks that are not Recharts), and `chart-parts` (grid, mono ticks, the 2px gap, rounded segments, the Recharts tooltip).
- **Charts:** shadcn's chart component over Recharts. Series colours are the `--chart-cat-*` tokens, fixed by provider; success, marigold and destructive are for worked, retried and failed only. Only the outermost segment of a stack is rounded, the grid is recessive, there are no dual axes, every chart has a hover tooltip and a table view, and a legend whenever there are two or more series. A call-time bar is one bar as long as the p95 that draws the median and the p95 tick together, so both share one scale.
- **Overview:** health pills, `Today / 7 days / 30 days` (`?range=`, default 7 days), four tiles (lessons started with a sparkline, finished as x / y with a meter, AI spend with the month's budget meter, model calls that worked with a sparkline), Daily AI spend (stacked by provider), Where lessons stop (funnel), Needs attention (each with a button to the page that fixes it) and Slowest steps (p95). Health and attention are polled every minute. A changed range keeps the old numbers, dimmed, until the new ones arrive.
- **Usage & cost:** filters (range with custom dates, provider, model, step, outcome; all in the address, a custom range is written once both dates are valid), four tiles, Call time by model (median bar, p95 tick), Calls by outcome (100% bars of worked, after a retry, failed), the sortable By lesson step table with a spend bar, and Export CSV (a link to `/api/console/usage/export.csv` with the same filters).
- **Known limits:** Export CSV is a plain download link, so if the access cookie has just expired it fails like any download until the page next refreshes the session.

## Console: Models, Model routing and Lesson settings (`/console/models`, `/console/routing`, `/console/settings`)

Built from the "Models", "Model routing" and "Lesson settings" pages of [socra-admin-mockup.html](design/mockups/socra-admin-mockup.html), in `components/console/models/`, `routing/` and `settings/`. Each page's rules live in classes in `lib/` (all tested with `bun test`); the components only draw.

- **Models:** a card per provider (its fixed colour from `ProviderSeries`, "Key set" / "Key missing" / "Disabled", the environment variable that holds the key and never the key, rate limit, models count, 7-day spend) with an Edit dialog (rate limit, address for the kinds that take one, switch). The models table shows capability chips, context, $ per million tokens in and out, the limit and the last test (works with its time, failed with its reason, not tested, no key); under 768px the detail folds under the name. **Test** and **Test all models** call the probe endpoint through `ProbeQueue`, two at a time, and put each result on its row as it arrives (the cache row is updated; the server keeps the result too). Add and Edit share one dialog (`ModelForm` checks the numbers, prices and default parameters before sending, and an edit sends only what changed). Delete asks first; a `409 model_in_use` shows "Used by: …" inside the dialog and in a toast.
- **Model routing:** steps grouped by phase, each row with its key, description, effort chip (or "off") and its chain as chips with arrows; the selected step is in `?node=` (only a step that exists). The editor changes a **local copy**: the enabled switch (disabled, with the reason, for a required step), effort, attempts and timeout, and the chain as a keyboard-sortable list (`@dnd-kit`; focus the handle, Space, arrow keys, Space; or the ↑ and ✕ buttons; a step always keeps one model), "Tried first / Used if #n fails", price, and "+ Add fallback" (only models that are on and whose provider key is set). A sticky bar says "Unsaved changes · step, step" with Discard and Save routing; **Save** sends one `PUT` per changed step (`RoutingSaver`), keeps the steps that saved, and shows the reasons for the ones the API refused on the step and in its row. Clicking a link to another page with unsaved edits asks first, and closing the tab gets the browser's own warning (the Back button is not caught: Next.js has no hook for it). **Apply a profile** asks the preview endpoint, lists each step it would change (now and then) and any it cannot apply, and **loads** them into the local copy; nothing is saved until Save routing.
- **Lesson settings:** the four sections of the mockup with the same help text, validation messages beside the boxes (ranges the model sets, and two checks the API does not make yet: the test maximum below the minimum, and a "foundations first" cut-off above the number of questions), and licence and source toggles. The right-hand panel "Where learners go" (`FlowBands`) is drawn from the **unsaved** values, a box that is not yet a number counting as its saved value, and states the ranges in words (foundations marigold, lesson teal, study sheets grape). Save sends a `PATCH` with only the changed fields; the toast says "Settings saved. New lessons will use them."

| Class (`lib/`) | What it does |
|---|---|
| `ModelCatalog` | The words of the Models page: provider names and colours, a provider card, capability chips, context ("131k"), prices, the last test, the "Used by: …" reason for a refused delete, and the cache row with a fresh test result |
| `ProbeQueue` | Runs model tests two at a time, reports each start and result, turns a test that could not be sent into a failed result, and can be stopped |
| `ModelForm`, `ProviderForm` | The forms' starting values, what is wrong with them (in plain words), and the request that saving sends (only what changed for an edit) |
| `RoutingDraft` | The local edits to a step (reorder, move up, remove, add, which models can be added) and which steps differ from what is saved |
| `RoutingProfile` | A profile preview as a list of changes (blocked ones with the reason) and its merge into the local edits |
| `RoutingSaver` | One `PUT` per changed step; keeps each step's outcome apart; writes the toast |
| `RoutingView` | Phase names, effort chip, chain chips, captions and price for the page, and `?node=` |
| `FlowBands` | Where each quick-check score goes (the same rules as `RoutingPolicy` on the server) and the legend in words |
| `FlowSettingsForm` | The settings form: text boxes in, checks, the patch of what changed, the unsaved fields |
| `ConsoleFailure` | A failed console request as one sentence and the API's messages per field |
| `UnsavedGuard` | Whether a click would leave a page with unsaved changes (only a plain click to another page of this site) |

## Console: Learners and Change log (`/console/learners`, `/console/audit`)

Built from the Learners and Change log pages of [socra-admin-mockup.html](design/mockups/socra-admin-mockup.html), in `components/console/people/`. Both pages only read, so there is no draft or save bar.

- **Learners:** four tiles (Learners with those new this week, Finished onboarding as a share, Active this week, Most common level and class), a search box for name or email (written to `?q=` a moment after typing stops; back and links move the box), and a table of name and email with a Staff badge, Studies, Goal, Language, Lessons, Last active (the exact time on hover), an Onboarding pill and "Open in Django admin". Pages of 25 with "Show more". The columns do not sort: the API orders by when they joined, and sorting only the loaded rows would mislead. The tiles read their own query (the summary and the newest 100), so searching does not change them.
- **Django admin link:** `NEXT_PUBLIC_DJANGO_ADMIN_URL` (default `${NEXT_PUBLIC_BACKEND_URL}/admin`; [local-setup.md](local-setup.md)) is read in `learners-table.tsx`. With no usable value there is no link.
- **Change log:** newest first, 50 at a time. Each entry has the actor's initial, a sentence (targets in `<code>`), the time relative with the exact time on hover, and "Show changes (n)" which opens a Field / Before / After table. A model that was only tested is named by looking its id up in the models list, since the entry keeps no snapshot of it. The area filter (All, Routing, Models, Settings, Runs) lives in `?area=`.
- **Known limit:** the API has no area filter, so the area is applied to the entries loaded so far; with a filter on, "Show more" is how to look further back, and the empty state says how many entries it looked through.

## Console: Lesson runs (`/console/runs`)

Built from the "Lesson runs" page of [socra-admin-mockup.html](design/mockups/socra-admin-mockup.html), in `components/console/runs/`; `app/console/(shell)/runs/page.tsx` only mounts `RunsView` inside the `Suspense` that `useSearchParams` needs.

- **List:** status tabs (All, Running, Failed · n, Finished), a job select and a search box, all in the address. Rows take focus and open on Enter or Space or a click. The Failed count is read from the first 100 failed runs ("100+" past that). "Show more runs" follows the API's cursor. Under 768px the job, time, calls, cost and start fold into a line under the topic, so there is no sideways scroll.
- **Detail:** beside the table from 1180px, under it below that (selecting a row then scrolls it into view). It shows the status, topic, learner, job and start, the Time, Calls and Cost tiles, "What went wrong" with a Copy button, the Timeline (hover or focus a lane for its node, result, start and time), the last model calls, and the actions: Retry from checkpoint (when `can_retry`), Stop run (when `can_cancel`, behind a confirm dialog), Open lesson (new tab) and Copy run ID. A retry opens the new run.
- **Live:** a run that is queued or running is followed by `RunFollower`. The events stream (`/runs/{id}/events`) is authorised for the run's owner only, so for another learner's run it is refused and the panel polls the console instead (every 3 seconds, 5 while the stream is open). When a followed run ends, the list refreshes.
- **Known limits:** Open lesson goes to the learner's page `/lessons/{id}`, which is also owner-only, so it shows "couldn't find this lesson" unless the staff member owns the lesson.
