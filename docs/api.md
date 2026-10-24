# API reference

Base path: `/api` (Django, port 8000). A Next.js route handler proxies `/api/*` to Django, so the browser only calls same-origin `/api/...`.

## Conventions

- **Interactive docs**: Swagger UI at `/api/docs`, ReDoc at `/api/redoc`, OpenAPI 3 schema at `/api/schema` (drf-spectacular; assets are served locally through the sidecar package). Every endpoint is annotated with `@extend_schema` (tags, request and response serializers, error responses), so Swagger is the source of truth for request and response shapes.
- **Paths have no trailing slash.**
- **System**: `GET /api/health` returns database, Redis, and Celery worker status (`200` ok, `503` degraded).

- JSON with `snake_case` fields.
- **Auth**: simplejwt tokens in httpOnly, `SameSite=Lax` cookies set by the API. JavaScript never sees a token. Cookies are used because `EventSource` can't send headers.

  | Cookie | Contents | Path | Lifetime |
  |---|---|---|---|
  | `lc_access` | access JWT | `/` | `JWT_ACCESS_MINUTES` (30) |
  | `lc_refresh` | refresh JWT, rotated on every refresh, with the old one blacklisted | `/api/auth` | `JWT_REFRESH_DAYS` (7) |
  | `lc_session` | `1`: the "signed in" marker for the Next.js route guard | `/` | refresh lifetime |
  | `lc_onboarded` | `1` once the profile is complete (route-guard marker) | `/` | refresh lifetime |

  `CookieJWTAuthentication` accepts `Authorization: Bearer <access>` first, which is useful for scripts and needs no CSRF, and falls back to the `lc_access` cookie. The markers carry no authority. `Secure` is set when `AUTH_COOKIE_SECURE=true`.
- **Rate limits**:
  - `auth`: register and login, per client address (`AUTH_THROTTLE_RATE`, default `20/min`)
  - `auth_account`: login attempts per email address, whatever the client (`AUTH_ACCOUNT_THROTTLE_RATE`, `10/min`)
  - `auth_refresh`: token refresh, per client (`AUTH_REFRESH_THROTTLE_RATE`, `60/min`)

  The client address is the `X-Forwarded-For` entry added by the Next.js proxy (`TRUSTED_PROXY_COUNT=1`). The API port is bound to localhost, so nobody can reach Django directly with a forged header.
- **CSRF**: unsafe methods send `X-CSRFToken`, taken from the `csrftoken` cookie (`GET /auth/csrf` sets it). This is enforced for every cookie-authenticated request and for the auth endpoints; Swagger UI adds the header automatically.
- **Ownership**: every lesson-scoped route returns `404` unless `lesson.owner == request.user`. A malformed id is also a `404`.
- **Rate limit** `lesson_create`: starting lessons, per user (`LESSON_CREATE_THROTTLE_RATE`, `30/hour`), because each lesson costs model calls.
- **Lesson errors** (`code`): `400 invalid_answers`, `404 not_found`, `409 wrong_stage` · `already_attempted` · `not_attempted` · `run_in_progress` · `run_ended`, `503 llm_not_configured` (no model is bound for the first step) · `queue_unavailable` (the broker is down; the lesson is failed so Retry works later).
- **Errors**: `{"detail": "...", "code": "...", "fields": {...}}`.
- **Pagination**: cursor-based, `?cursor=&page_size=20` → `{results, next, previous}`.

## Auth and profile

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/auth/csrf` | none | `204`, sets `csrftoken` |
| POST | `/auth/register` | `{email, password, name}` | `201 {user}`, sets cookies |
| POST | `/auth/login` | `{email, password}` (email is case-insensitive) | `200 {user}`, sets cookies; `401 invalid_credentials` |
| POST | `/auth/refresh` | none (uses `lc_refresh`) | `200 {user}`, rotates cookies; `401 session_expired` clears them |
| POST | `/auth/logout` | none | `204`, clears and blacklists |
| GET | `/auth/me` | none | `{id, email, name, profile_complete}`, or `401` |
| GET | `/profile` | none | `Profile` |
| PUT | `/profile` | `Profile` fields; `education_level`, `learning_preference`, `goal` required | `200 Profile`, sets or clears `lc_onboarded` |
| PATCH | `/profile` | any subset (including `name`) | `200 Profile` |

## Lessons

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | `/lessons` | `?q=&stage=&cursor=` | paginated `LessonSummary[]` (own lessons only) |
| POST | `/lessons` | `{topic, user_context?}` | `202 {lesson_id, run_id}`: snapshots the registry and settings, and enqueues `start_flow` |
| GET | `/lessons/{id}` | none | `LessonDetail`: summary fields plus `user_context`, `error`, `warnings`, `assessment` (level, known concepts, gaps, start point, confidence; never the notes for the page writers), `prerequisites_to_cover` (names), `active_run_id` and `results` (the score of each quiz already answered, so a reload keeps them). Later phases add the content fields. |
| DELETE | `/lessons/{id}` | none | `204` (cancels any active run, deletes media files) |
| POST | `/lessons/{id}/retry` | none | `202 {run_id}`: only when `stage=failed` (`409` otherwise, or while a run is active); resumes from the last checkpoint. If the graph gave up after failed validations it resumes at the node that gave up; after a model failure it re-runs the failed node. |

### Quizzes (Stage A)

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/lessons/{id}/quizzes/{kind}` | none | `QuizForLearner`: questions **without** answers or explanations; `kind` = `diagnostic` \| `prerequisite` |
| POST | `/lessons/{id}/quizzes/{kind}/attempt` | `{answers: {question_id: 0-3 \| "dont_know"}}` | `202 {result: QuizResultSummary, run_id}`. Graded synchronously, then the graph resumes. `409` if already attempted or the lesson is not awaiting this quiz. `400` if any question is unanswered. |
| GET | `/lessons/{id}/quizzes/{kind}/review` | none | Questions with the learner's answers, correct answers, and explanations. Only after the attempt. |

```jsonc
// QuizForLearner
{ "quiz_id": "uuid", "kind": "diagnostic",
  "questions": [{ "id": "q1", "band": "basic", "question": "...", "options": ["...", "...", "...", "..."] }],
  "allow_dont_know": true }

// QuizResultSummary
{ "correct": 6, "total": 10, "dont_know": 2,
  "by_band": { "basic": [2,2], "easy_moderate": [2,2], "moderate": [1,2], "moderate_hard": [1,2], "hard": [0,2] },
  "route": "lesson" }          // "prerequisite" | "lesson" | "mastery"
```

### Mastery choice and study materials

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/lessons/{id}/choice` | `{kind: "cheat_sheet" \| "revision_sheet" \| "practice_sheet"}` | `202 {run_id}`: resumes the flow. Only when `stage=awaiting_choice`. |
| POST | `/lessons/{id}/materials` | `{kind}` | `202 {run_id}`: requests an *additional* sheet later (runs the `study_material` graph) |
| GET | `/lessons/{id}/materials/{kind}` | none | `StudyMaterial`. For a practice sheet, solutions are omitted until `?reveal=question_id` (or `?reveal=all`). |

### Lesson document and final test

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/lessons/{id}/document` | none | `{code, code_version, data: LESSON}`. `data` holds pages, final test (without answers), and media as signed URLs. |
| POST | `/lessons/{id}/repair` | `{error: {message, stack?, page?}, code_version}` | `202 {run_id}`. `409` if `code_version` is stale or `max_auto_runtime_repairs` is reached. |
| POST | `/lessons/{id}/test/submissions` | `{answers: {question_id: value}}` | `202 {submission_id, run_id}`. MCQ and numerical answers are graded instantly; the rest go through `test.grade`. |
| GET | `/lessons/{id}/test/submissions/{sid}` | none | `{status, result: GradeReport \| null}` |
| GET | `/lessons/{id}/versions` | none | `LessonVersion[]` |
| POST | `/lessons/{id}/versions/{n}/restore` | none | `200` |

### Media

| Method | Path | Response |
|---|---|---|
| GET | `/media/{asset_id}?exp=&sig=` | The file. No cookie needed; the HMAC signature and expiry are checked. |

## Runs and progress (SSE)

| Method | Path | Response |
|---|---|---|
| GET | `/runs/{id}` | `{id, lesson_id, graph, trigger, status, node_status, error}` |
| GET | `/runs/{id}/events` | `text/event-stream` (works with a browser's `EventSource`, which sends `Accept: text/event-stream`) |
| POST | `/runs/{id}/cancel` | `202`: stops the run after its current step and marks the lesson failed, so it can be retried. `409` once the run has ended. |

The stream subscribes to Redis `run:{id}:events` *before* it sends a `snapshot`, so nothing published in between is lost; it sends `: ping` every `SSE_HEARTBEAT_S` (15) seconds and closes after a terminal event. A client that connects after the run ended gets the snapshot and then its terminal event. Because the stream starts with a snapshot, a reconnecting client catches up from `node_status`.

| event | data | Terminal |
|---|---|---|
| `snapshot` | `{status, stage, lesson_id, node_status, error, awaiting}` | |
| `node` | `{node, status, attempt?, reason?}` | |
| `model` | `{node, model, kind: "retry" \| "fallback", reason, attempt?, fallback_index?}`: a model call was retried or fell back (`node` is the registry node key) | |
| `warning` | `{message}` | |
| `awaiting_input` | `{kind: "diagnostic" \| "prerequisite" \| "mastery_choice", quiz_id?}`: published by the runner when the graph pauses, after the run is marked `paused` | ✓ |
| `done` | `{lesson_id, stage}` | ✓ |
| `error` | `{message, code}` | ✓ |
| `cancelled` | `{}` | ✓ |

The UI groups nodes into steps:

- **Preparing quiz**
- **Assessing your level**
- **Planning** → **Writing pages** → **Finding media & building interactives** → **Checking content**
- **Building lesson** → **Testing in sandbox**
