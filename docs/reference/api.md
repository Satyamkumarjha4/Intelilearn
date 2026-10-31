# API reference

Base path: `/api` (Django; port 8000 inside its container, `BACKEND_PORT` on the host). A Next.js route handler proxies `/api/*` to Django, so the browser only calls same-origin `/api/...`.

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

  The client address is the first `X-Forwarded-For` entry the Next.js proxy sees (`TRUSTED_PROXY_COUNT=1`). The proxy keeps that first entry and forwards it as the only one. Next fills the header from the connection only when the client sent none, so **a client that sends its own `X-Forwarded-For` chooses the address these limits count it under**, and these per-address limits slow honest clients but do not stop a deliberate one. The per-account login limit, and the per-user limits below (`lesson_create`, `test_submit`, `topic_suggestions`, `console`), count by account and are not affected. Keeping the API port bound to localhost stops direct requests with a forged header, but not requests through the proxy. A real deployment needs an edge proxy that overwrites the header.
- **CSRF**: unsafe methods send `X-CSRFToken`, taken from the `csrftoken` cookie (`GET /auth/csrf` sets it). This is enforced for every cookie-authenticated request and for the auth endpoints; Swagger UI adds the header automatically.
- **Idempotency**: `POST /lessons` and `POST /lessons/{id}/materials` accept an optional `Idempotency-Key` header (1 to 128 printable characters without spaces; otherwise `400 invalid_idempotency_key`). A repeat of the same request by the same learner, with the same key and body, within `IDEMPOTENCY_TTL_S` (24 hours) returns the first `2xx` answer with `Idempotent-Replayed: true` and starts nothing. A repeat while the first is still being handled is `409 request_in_progress`. Only successful answers are kept, so a failed request can be repeated with the same key.
- **Refused actions**: an action that starts paid work asks the action gate first (`ACTION_GATE`, see [design.md](../architecture/design.md#418-lessons-the-action-gate-phase-9-metering-seam)). The default gate allows everything, so nothing returns a refusal today. A gate that says no raises `ActionRefused`, which is the usual `{detail, code}` body (status `403` for now; a credits feature will use `402` later). It is possible on `POST /lessons`, `POST /lessons/{id}/quizzes/diagnostic/attempt` (nothing is stored, so the answers can be sent again), `POST /lessons/{id}/choice`, `POST /lessons/{id}/materials` and `POST /lessons/{id}/retry` (the lesson stays failed).
- **Ownership**: every lesson-scoped route returns `404` unless `lesson.owner == request.user`. A malformed id is also a `404`.
- **Rate limit** `console`: the staff-only console API, per staff member (`CONSOLE_THROTTLE_RATE`, `120/min`). A refused `404` does not use it up.
- **Rate limit** `lesson_create`: starting lessons, per user (`LESSON_CREATE_THROTTLE_RATE`, `30/hour`), because each lesson costs model calls.
- **Rate limit** `test_attempt`: starting an attempt, per user (`TEST_ATTEMPT_THROTTLE_RATE`, `30/hour`), because a retake costs a generation. A lesson also allows `retakes_per_day` (3) retakes in 24 hours: past that, `429 retake_limit`.
- **Console errors** (`code`): `404 not_found` for anyone who is not staff (signed in or not) and for a missing target, `409 not_retryable` · `model_in_use` (carries `nodes`) · and the lesson errors `wrong_stage` · `run_in_progress` · `run_ended` for retry and cancel.
- **Lesson errors** (`code`): `400 invalid_answers`, `404 not_found`, `409 wrong_stage` · `already_attempted` · `already_submitted` (carries `submission_id`) · `attempt_sealed` · `locked` · `not_failed` · `not_attempted` · `run_in_progress` · `run_ended`, `429 retake_limit`, `503 llm_not_configured` (no model is bound for the first step) · `queue_unavailable` (the broker is down; the lesson is failed so Retry works later).
- **Errors**: `{"detail": "...", "code": "...", "fields": {...}}`; a few carry more for the client to act on (`already_submitted` adds `submission_id`).
- **Pagination**: cursor-based, `?cursor=&page_size=20` → `{results, next, previous}`.

## Auth and profile

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/auth/csrf` | none | `204`, sets `csrftoken` |
| POST | `/auth/register` | `{email, password, name, accept_terms}` (`accept_terms` must be `true`: the person is 18 or older, or a parent or guardian agreed to the Terms of Use and Privacy Policy) | `201 {user}`, sets cookies. Without the confirmation: `400` with `fields.accept_terms: ["Please confirm to continue."]` and nothing is created. The time and the version of the terms (`User.TERMS_VERSION`, "2026-10-25") are kept on the user. |
| POST | `/auth/login` | `{email, password}` (email is case-insensitive) | `200 {user}`, sets cookies; `401 invalid_credentials` |
| POST | `/auth/refresh` | none (uses `lc_refresh`) | `200 {user}`, rotates cookies; `401 session_expired` clears them |
| POST | `/auth/logout` | none | `204`, clears and blacklists |
| GET | `/auth/me` | none | `{id, email, name, profile_complete, is_staff}`, or `401`. `is_staff` says whether the person may use the [console](#console-staff-only) (the same user object is returned by login, register and refresh) |
| GET | `/profile` | none | `Profile` |
| PUT | `/profile` | `Profile` fields; `education_level`, `learning_preference`, `goal` required | `200 Profile`, sets or clears `lc_onboarded` |
| PATCH | `/profile` | any subset (including `name`) | `200 Profile` |
| GET | `/profile/options` | none (no sign-in) | `{education_level, learning_preference, goal, preferred_language}`: each a list of `{value, label}` in display order, exactly what the profile accepts. The screens read their choices from here (a language outside the list, or notes over 2000 characters, is a `400`) |

## Landing page

| Method | Path | Query | Response |
|---|---|---|---|
| GET | `/landing/demo-question` | `exclude?` (a question id not to return) | `200` one random active question for the landing page's try-it card: `{id, subject, level_label, band (1–5), question, options (exactly 3), correct_index, outcome_right, outcome_wrong}`, each outcome `{level (1–5), level_label, lesson_start}`. No sign-in, never cached (`Cache-Control: no-store`), 60 a minute per client address (`LANDING_DEMO_THROTTLE_RATE`, `429 throttled`). `exclude` that is not a whole number is a `400`; with only one question active, `exclude` is ignored. `404` when no question is active |

The card judges the answer in the browser (the answer is not secret: it is a demo), so `correct_index` is part of the response. See [frontend.md](frontend.md#the-landing-page).

## Onboarding

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/onboarding/topic-suggestions` | `{education_level, goal, preferred_language?="en", grade_or_year?, field_of_study?, page?=0}`. Sent before the profile is saved; the choices are the profile's own (`400` with the readable "Please choose one of the options." otherwise); `grade_or_year` ≤ 100 and `field_of_study` ≤ 150 characters, `page` 0 to 10000 | `200 {source, topics, has_more}`: `source` is `catalogue`, `ai` or `fallback`; `topics` is exactly four `{title, title_en, subject, reason}` (`title` and `reason` in the learner's language, `title_en` always English); `has_more` is true when the list is longer than four. `429 throttled` past 30 requests a minute per learner (`TOPIC_SUGGESTIONS_THROTTLE_RATE`) |

Never a `5xx` for a model's sake: when a model fails or times out, the answer is `200` with English catalogue topics and `source: fallback`. See [onboarding.md](onboarding.md) for how the topics are chosen.

## Lessons

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | `/lessons` | `?q=&stage=&cursor=` (`stage` takes one stage or several, comma-separated) | paginated `LessonSummary[]` (own lessons only): the summary fields plus `test_status` (how the **latest attempt** stands: `not_started \| generating \| in_progress \| grading \| graded \| failed`), `test_score` and `latest_score` (`{awarded, available}` of the latest graded attempt, so a retake in progress does not hide it; `null` before any), `best_score` (the best graded attempt by percent), `attempts_count` (attempts that have their questions), `has_open_attempt` and `material_count` (study sheets), fetched for the whole page at once |
| POST | `/lessons` | `{topic, user_context?, entry?, self_rating?, intent?, origin?, recommended_from?}`; optional `Idempotency-Key` header. `entry` is `diagnostic` (default: the quick check) or `self_rating`, which needs `self_rating`: stars from 0.5 to 5 in half steps (stored as halves; `true`, `0`, `5.5` and `2.3` are refused, and a rating without its entry is too). `intent` can only be `lesson` for now. `origin` is `direct` (default) or `recommendation`, which needs `recommended_from: {attempt_id, topic}`: the server checks that it is the caller's own graded attempt and that it listed that topic (`400` naming `recommended_from` otherwise, with one message for a missing and another learner's attempt). `followup` and `quiz_result` are `400` here. Old bodies keep working | `202 {lesson_id, run_id}`: snapshots the registry and settings, and enqueues `start_flow`. A self-rated lesson has no quiz: it goes straight to building, and a Beginner's prerequisites are planned. `503 llm_not_configured` also when the planner (`lesson.plan`, and `prerequisites.plan` for a Beginner's stars) has no model |
| GET | `/lessons/{id}` | none | `LessonDetail`: summary fields plus `user_context`, `error`, `warnings`, `assessment` (level, known concepts, gaps, start point, confidence; never the notes for the page writers), `prerequisites_to_cover` (names), `active_run_id`, `results` (the score of each quiz already answered, so a reload keeps them), `followup_of` (`{id, title, level}` of the lesson this was made from, `level` being what kind of follow-up this is, or `null` for a lesson that is not one or whose parent was deleted), `followups` (`{foundation, advanced}`, each `{id, title}` or `null`; the title is the topic until the plan has written one), `entry`, `intent`, `origin`, `level_source` and `self_rating` (stars, or `null`), `mastery_options` (`lesson_or_sheets`, or `three_sheets` for a lesson that was already waiting at the old choice; the page shows the cards it was waiting at), the attempt summary fields above (`test_status`, `test_score`, `latest_score`, `best_score`, `attempts_count`, `has_open_attempt`). Later phases add the content fields. |
| DELETE | `/lessons/{id}` | none | `204` (cancels any active run, deletes the lesson's media files, LangGraph checkpoints and model-call log along with the lesson) |
| POST | `/lessons/{id}/retry` | none | `202 {run_id}`: only when `stage=failed` (`409` otherwise, or while a run is active); resumes from the last checkpoint. If the graph gave up after failed validations it resumes at the node that gave up; after a model failure it re-runs the failed node; after the learner's Stop the lesson goes back to the stage it was stopped in and carries on from its checkpoint with the answer it had (see [lesson-graph.md](../architecture/lesson-graph.md)). |

### Follow-up lessons

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/lessons/{id}/followups` | `{level: "foundation" \| "advanced"}`; optional `Idempotency-Key` header | `202 {lesson_id, run_id}`: a lesson of its own made from a **ready** lesson of the caller's, once for each level. Its topic is `Foundations of X` or `Advanced X` (a suffix, `(2)`, when another of the learner's lessons has that name; it is never linked to one that exists), its level is fixed by what it is for (Foundation: Beginner, Advanced: Expert), it has `entry` and `origin` `followup`, no quick check and no rating, and a Beginner's prerequisites are planned as usual. It counts against the new-lesson rate limit and asks the action gate for `lesson.followup` (hint `followup_level`). `409 already_exists {detail, code, lesson_id}` when that level was made (the client opens that lesson; nothing is asked or made), `409 wrong_stage` unless the parent is `ready`, `400` for a missing or unknown `level`, `404` for another learner's lesson, `503 llm_not_configured` when the lesson planner (and, for Foundation, the prerequisite planner) has no model, `429`. `POST /lessons` still refuses `origin: followup`. |

**The offer** on a graded attempt (`followup`, in the attempt and in the submit answer): `{kind, action, lesson_id}`, decided by the server (spec 3.3). `kind` is `foundation`, `advanced` or `inline_suggestion`. `action` is `generate` (make that lesson), `revisit` (a Foundation lesson that exists, in `lesson_id`), `open` (an Advanced lesson that exists) or `revisit_or_related` (the quiet note for a learner who rated themselves low and failed). A Fail gets the Foundation offer until the learner has passed once (a score at or above the lesson's Fail line on an earlier graded attempt), except from a learner who rated themselves low (only the note) and an attempt of blank answers (nothing); an Excellent gets the Advanced offer on every such attempt except from a learner who rated themselves high (nothing). A learner's category comes from their stars, or from the level of their lesson (a Foundation follow-up is a Beginner lesson and an Advanced one an Expert lesson, so chains of follow-ups stop on their own).

### Quizzes (Stage A)

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/lessons/{id}/quizzes/{kind}` | none | `QuizForLearner`: questions **without** answers or explanations; `kind` = `diagnostic` \| `prerequisite` |
| POST | `/lessons/{id}/quizzes/{kind}/attempt` | `{answers: {question_id: 0-3 \| "dont_know"}}` | `202 {result: QuizResultSummary, run_id}`. Graded synchronously, then the graph resumes. `409 already_attempted` for a second attempt (checked first, so it stays the answer once the lesson has moved on), `409 wrong_stage` if the lesson is not awaiting this quiz. `400` if any question is unanswered. |
| GET | `/lessons/{id}/quizzes/{kind}/review` | none | `{quiz_id, kind, submitted_at, questions: [{id, band, question, options, correct_index, explanation, answer (an option index or "dont_know"), correct}], result}`: each question with the learner's own answer next to the right one. `409 not_attempted` before the attempt. |

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
| POST | `/lessons/{id}/choice` | `{choice: "lesson" \| "sheets"}`, or (for a lesson already waiting at the old three-sheet choice) `{kind: "cheat_sheet" \| "revision_sheet" \| "practice_sheet"}` | `202 {run_id}`: resumes the flow. `lesson` continues with an **Expert lesson** (it has a test); `sheets` writes the **cheat sheet and the revision sheet** and ends there, `ready` with route `mastery` and no test; a kind writes that one sheet as before. `lesson.continue` is asked with `choice` (`lesson` or `sheets_only`) and `perfect: true`; a refusal changes nothing and the lesson stays at the choice. `409 wrong_stage` unless `stage=awaiting_choice`; `409 run_in_progress`; `400` unless exactly one of `choice` and `kind` is sent and known. |
| POST | `/lessons/{id}/materials` | `{kind}`; optional `Idempotency-Key` header | `202 {run_id}`: requests an *additional* sheet (runs the `study_material` graph in its own thread; the lesson stays `ready`). Only for a ready mastery lesson (`409 wrong_stage`), once per kind (`409 already_exists`), one at a time (`409 run_in_progress`). A failed extra run ends with its reason and does not fail the lesson; ask again. |
| GET | `/lessons/{id}/materials/{kind}` | `?reveal=<question id>` (repeat it, or comma-separate) or `?reveal=all` | `{kind, content, solutions}`. The content is the sheet; for a practice sheet its questions have **no solution fields** and `solutions` holds `{question_id: solution}` for the revealed ones. `404` if the sheet does not exist. |
| POST | `/lessons/{id}/materials/practice_sheet/grade` | `{answers: {question_id: option index \| list of option indices (multiple select) \| number \| text}}` | `200 {score: {awarded, available, open_marks, correct, marked}, results: [{id, correct, marks, awarded, solution}]}`. Multiple-choice and numerical answers are marked (a numerical answer may be typed as `4`, `4.0` or `4 steps`; the tolerance is absolute and inclusive); short, long and code answers get `correct: null` and show their solution for self-checking. Nothing is stored, so practice can be repeated. |

`LessonDetail.materials` lists the kinds a lesson already has.

**Kinds of question** (practice sheets and the final test; `QuestionType` in `graph/questions/`). What a question shows before it is answered is an allowlist per kind, so a new field stays private until it is added: every kind has `id`, `type`, `concept`, `difficulty` (`easy`, `basic`, `standard`, `difficult` or `expert`) and `marks`, plus

| `type` | Shown before answering | Answer to send | Marks |
|---|---|---|---|
| `mcq` | `options` (4) | the option index | 1, or 2 when difficult or expert |
| `msq` ("choose all that apply") | `options` (4 to 6) | a list of option indices | 2 / 3; all right is full, at least half of the right ones and none wrong is full minus 1, fewer is 1, any wrong option or none is 0 |
| `numerical` | `unit`, `decimal_precision` (0 to 6, a **hint** for the input: it never rejects an answer, only the tolerance decides) | a number or text such as `4`, `4.0`, `4 steps` | 2 / 3 |
| `short_answer`, `long_answer` | nothing more | text | 2 / 3 and 5 / 6, in criteria that each carry whole marks |
| `code` | `language`, `starter_code` | text | only in lessons from before; they keep their stored marks |

Marks come from `MarksPolicy`, never from a model, and a stored question keeps the marks it was stored with. The solution (shown after answering) holds `correct_index` or `correct_indices`, `answer` and `tolerance` and `unit`, or `model_answer` and `criteria`; `answer_expr` is never sent. A model-graded row of a result has a `criteria` list with what each point earned.

### Lesson document and test

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/lessons/{id}/document` | none | `{code, code_version, has_embedded_test, data: LESSON}`. `data` holds the three pages, the final test (without answers) and media as signed URLs. `has_embedded_test` is true for a lesson made before the test became its own screen: its code still has a `test` page, which the viewer hides (a repair removes it). New lessons have three pages and the flag is false. `409 wrong_stage` until the lesson is ready. |
| POST | `/lessons/{id}/repair` | `{error: {message, stack?, page?}, code_version}` | `202 {run_id}`: queues the `runtime_repair` graph (a new `code_version` on success; a failed run leaves the code alone). `409 stale_code_version`, `409 repair_limit_reached` (each request counts against `max_auto_runtime_repairs`), `409 wrong_stage`, `409 run_in_progress`; `400` for a message over 2000 characters or a missing field. |
| GET | `/lessons/{id}/test` | none | `{questions: [{id, type, question, marks, options?, unit?, decimal_precision?, language?, starter_code?}], total_marks, attempt: null \| {id, attempt_no, status, started_at, submitted_at}, answers: {question_id: answer}, next_attempt_no, submission: null \| {id, status, submitted_at}}`: the **open** attempt's questions without answers, marking schemes, explanations or concepts, and the answers already saved (locked), so a refresh resumes; `questions: []` when no attempt is open or while a retake's questions are being written. **No side effects**: it never starts anything. `submission` is the latest attempt. `409 wrong_stage` until the lesson is ready, and for a mastery lesson. |
| POST | `/lessons/{id}/test/attempts` | none; optional `Idempotency-Key` header | **Starts an attempt**, or returns the open one (so a refresh resumes and a double click is one attempt). Attempt 1 is part of the lesson: `201 {attempt_id, attempt_no, status: "in_progress", run_id: null, questions, total_marks, answers, started_at}` from the questions the lesson was built with (a lesson from before the fixed test snapshots its old test). **Attempt 2 and later always generate** a fresh set: the attempt is created `generating`, the action gate is asked for `test.retake` (nothing is created if it refuses), and the reply is `202` with `status: "generating"`, `questions: []` and the `run_id` of the `question_bank` run to follow; when the run ends the attempt is `in_progress` (read `GET …/test`), or, if it failed or was stopped, it is gone. A repeat while it waits returns the same attempt and run (`202`), an open in-progress attempt `200`. `409 wrong_stage`; `429 throttled` over `TEST_ATTEMPT_THROTTLE_RATE`, `429 retake_limit` past `retakes_per_day`. |
| GET | `/lessons/{id}/test/attempts` | none | `{attempts: [{id, attempt_no, status, awarded, available, percent, band, duration_s, submitted_at}], trend: {series: [{attempt_no, awarded, available, percent, delta_previous, delta_best}], best_attempt_no}}`, oldest first. The trend is computed here from whole marks: `delta_previous` is the change in percentage points since the previous graded attempt, `delta_best` the change against the best of the earlier ones (`null` for the first); of equal best scores the earlier is the best. |
| GET | `/lessons/{id}/test/attempts/{aid}` | none | One attempt, read-only: `{id, attempt_no, status: generating \| in_progress \| grading \| graded \| failed, error, questions, answers, result: ScoreCard \| null, awarded, available, band: "" \| fail \| normal \| excellent, duration_s, followup, started_at, submitted_at, graded_at}`. `questions` (what the attempt asked, with no answer key; the same fields as above) is empty while the attempt is open: the open attempt's questions come from `GET …/test`. `ScoreCard`: `{complete, score: {awarded, available, percent}, questions: [{id, type, concept, marks, awarded (null while a model is grading it), correct, graded_by: auto \| model \| none, feedback, solution, criteria?}], topics_to_revisit}`. `failed`: the written answers of a legacy attempt could not be graded (`error` says why); grade again with `regrade`. `404` for an unknown attempt or another lesson's. |
| PUT | `/lessons/{id}/test/attempts/{aid}/answers/{qid}` | `{answer: number \| list of numbers \| text \| null}` | `200 {attempt_id, question_id, locked: true, answered}`. **Saves one answer and locks that question**, enforced on the server (forward-only): a second PUT for it is `409 locked`; `null` leaves it blank and locks it too. `400` for an unknown question or an answer of the wrong shape (a short list of option numbers, a number or text up to 10,000 characters); `409 attempt_sealed` once the attempt is over; `409 wrong_stage` while a retake is still being prepared. |
| POST | `/lessons/{id}/test/attempts/{aid}/submit` | `{answers?: {question_id: answer}}` (answers for questions that are not locked yet, such as the last card; a locked question keeps its saved answer) | **Seals the attempt**: missing answers are blank and score 0; an attempt of blank answers only is stored, scores 0 and is flagged (it gets no offer, so an empty submit cannot collect lessons). A lesson attempt is objective, so it is **graded in this request**: `200 {submission_id, attempt_id, attempt_no, run_id: null, status: "graded", awarded, available, band, followup, result: ScoreCard}`. Only a legacy attempt with open-ended questions answers `202` with a `run_id` (`status: "grading"`, `result.complete: false`). `followup` is the offer that follows the score (below), or `null`. `409 attempt_sealed` when it is over already (nothing changes), `409 wrong_stage` while preparing, `400` for an unknown question id or a bad answer. |
| POST | `/lessons/{id}/test/attempts/{aid}/regrade` | none | `202 {run_id}`: runs `grade_test` again on the stored answers and sets `status` back to `grading`. Only a legacy attempt can be `failed`. `409 not_failed` unless `status` is `failed`; `409 run_in_progress` while a run is active; `404` for an unknown attempt. |
| POST | `/lessons/{id}/test/submissions` | `{answers: {question_id: number \| list of numbers \| text \| null}}` | **Kept for the old test screen**: starts and submits the first attempt in one call, `202 {submission_id, attempt_id, attempt_no, run_id, status, awarded, available, band, followup, result}` (as the submit above). Only the first attempt: once the lesson has any attempt it is `409 already_submitted` `{detail, code, submission_id}` (nothing is stored). `400`, `409 wrong_stage`, `429` over `TEST_SUBMIT_THROTTLE_RATE`. Removed in a later release. |
| GET | `/lessons/{id}/test/submissions/{sid}` | none | The same as the attempt by id. |
| GET | `/lessons/{id}/test/submission` | none | The **latest** attempt (the highest `attempt_no`), as above. `404` before the first. |
| GET | `/lessons/{id}/versions` | none | `[{code_version, reason, created_at}]`, newest first. The code itself is not listed. A version is kept before each repair and each restore. |
| POST | `/lessons/{id}/versions/{n}/restore` | none | `200 {code_version}`: version `n` becomes current under a new `code_version`, and the code it replaced is kept. `404` for an unknown version (the current one has no row), `409 wrong_stage` / `run_in_progress`. |

### Media

| Method | Path | Response |
|---|---|---|
| GET | `/media/{asset_id}?exp=&sig=` | The file. No cookie needed; the HMAC signature and expiry are checked. |

## Runs and progress (SSE)

| Method | Path | Response |
|---|---|---|
| GET | `/runs/{id}` | `{id, lesson_id, graph, trigger, status, node_status, error}` |
| GET | `/runs/{id}/events` | `text/event-stream` (works with a browser's `EventSource`, which sends `Accept: text/event-stream`) |
| POST | `/runs/{id}/cancel` | `202`: stops the run after its current step and marks the lesson failed, so it can be retried; the run remembers where the lesson was, and Retry carries on from there. `409` once the run has ended. |

The stream subscribes to Redis `run:{id}:events` *before* it sends a `snapshot`, so nothing published in between is lost; it sends `: ping` every `SSE_HEARTBEAT_S` (15) seconds and closes after a terminal event. A client that connects after the run ended gets the snapshot and then its terminal event. Because the stream starts with a snapshot, a reconnecting client catches up from `node_status`.

| event | data | Terminal |
|---|---|---|
| `snapshot` | `{status, stage, lesson_id, node_status, error, awaiting, started_at}` (`started_at`: when the run began, else when it was queued) | |
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


## Console (staff only)

The API behind the staff console (`backend/console/`; `tag: console` in Swagger). Everything is under `/api/console/`.

- **Access**: `User.is_staff` only (`IsAdminUser`). Anyone else, signed in or not, gets the same `404 not_found` as a page that does not exist, on reads and writes alike, so the area does not announce itself. An invalid or expired token is still a `401`, so the silent refresh runs; but an access cookie that has just expired makes the request anonymous, which is a `404` here, so the frontend client (`ConsoleApi`) renews the session and tries a 404 once more. Cookie auth and CSRF are the usual ones. `120/min` per staff member. Responses are `Cache-Control: no-store`.
- **Secrets**: a provider is the *name* of its key's environment variable and `api_key_set` (whether it is set); a key's value is never returned, logged or audited.
- **Formats**: money is a USD decimal string with six places (`"0.012345"`), times are ISO 8601, lists of rows (`runs`, `providers`, `models`, `learners`, `audit`) use the usual cursor pagination (`?cursor=&page_size=`, `{results, next, previous}`), and errors have the usual `{detail, code, fields?}` shape.
- **Ranges** (`?range=`): `today` (since midnight UTC), `7d` (today and the six days before) and `30d`, each ending now. `GET /console/usage` and its CSV also take `range=custom` with `start` and `end` (dates, `YYYY-MM-DD`; whole days, both included, at most 366 days, in order), and default to `7d`. The *previous* period is the same length, ending where the range starts.
- **Calls**: a model call is one *attempt* (a retry, or the next model of the chain, is another call). It is `ok` (worked on attempt 1), `retried` (worked on attempt 2 or later) or `failed` (any other status), so the three add up to the calls made. A *fallback* is an attempt on the second or later model of a step's chain (`fallback_index` above 0) and a *retry attempt* one with `attempt` above 1, whatever came of them. Call times are of the calls that worked, as interpolated percentiles (Postgres `percentile_cont`). Rate-limit waits are part of `latency_ms`; `rate_limit_wait_ms` says how much.
- **Audit**: every request that changes something writes one `AuditEntry` (actor, action, target, before, after) in the same transaction as the change; refused requests and reads write none.

| Method | Path | What it does |
|---|---|---|
| GET | `/console/overview?range=` | `{range, period, health, lessons, spend, calls, daily_spend, daily_activity, funnel, slowest_steps, attention}`. `health`: the `/health` checks plus `workers` (Celery workers that answered). `lessons`: `started`, `finished` and `failed` in the range (a lesson counts where its row last changed to that stage) `previous_started` and `previous_finished` (the same counts for the equally long range before). `spend`: `range_total`, `per_lesson_avg` (over the lessons that made calls), `month_to_date` and `monthly_budget` (`CONSOLE_MONTHLY_BUDGET_USD`, default 25). `calls`: `total`, `ok`, `retried`, `failed`, `fallbacks`. `daily_spend`: 14 days (30 for `30d`), oldest first, empty days included, `[{date, by_provider: {key: amount}}]`. `daily_activity`: the same days, `[{date, lessons_started, calls_total, calls_worked}]`, for the sparklines. `funnel`: of the lessons started in the range, `started`, `quick_check_done`, `built` (ready, not a study sheet), `test_submitted`, `retested` (two or more attempts that are over), `followups_started` (a Foundation or Advanced lesson was made from it), `study_sheets` (ready by mastery), `failed_building`, `waiting` (for the learner). `slowest_steps`: the six steps with the highest p95 call time. `attention`: `[{kind, severity (error \| warning \| info), title, detail, link}]`, most serious first, from four rules: lessons failed in the last 24 hours (`lessons_failed`); a model failing more than 20% of at least 20 calls in the range (`model_failing`); calls today that waited for a rate limit (`rate_limit_waits`); a provider with models bound to a step but no API key (`provider_key_missing`) |
| GET | `/console/usage?range=&start=&end=&provider=&model=&node=&outcome=` | `{range, period, kpis, by_model, by_node}`. `kpis`: `calls`, `tokens_in`, `tokens_out`, `spend`, `median_latency_s`, `p95_latency_s` (null when nothing worked). `by_model`: `[{model, provider, median_s, p95_s, ok, retried, failed, calls, spend}]` (`calls` is `ok + retried + failed`). `by_node`: `[{node, calls, ok_pct (worked first time or on a retry), retries, fallbacks, tokens_k, spend, p95_s}]`. Busiest first. `outcome` is `ok`, `retried` or `failed`; an unknown value is a `400` |
| GET | `/console/usage/export.csv` | The calls the same filters select, one row per call, oldest first, streamed as `text/csv` with a download name. Columns: `created_at, node, provider, model, attempt, fallback_index, status, outcome, latency_ms, rate_limit_wait_ms, tokens_in, tokens_out, reasoning_tokens, tool_calls, cost, lesson_id, run_id, error`. Text a spreadsheet would run as a formula (starting `=`, `+`, `-`, `@`) gets a leading apostrophe |
| GET | `/console/runs?status=&graph=&q=` | Paged, newest first: `[{id, lesson_id, topic, learner_name, graph, trigger, status, stage, duration_s, calls, cost, created_at}]`. `status` and `graph` take one value or several separated by commas; `q` searches the topic, the learner's name and email. `duration_s` is null before the run starts and the age so far while it runs |
| GET | `/console/runs/{id}` | The row's fields plus `error`, `started_at`, `finished_at`, `timeline`, `model_calls` (the last 20, newest first: `{id, created_at, node, provider, model, attempt, fallback_index, status, outcome, latency_s, tokens_in, tokens_out, tool_calls, cost, error}`), `can_retry` and `can_cancel`. See the timeline below |
| POST | `/console/runs/{id}/retry` | The learner's Retry, as staff (`LessonService.retry`): `202 {run_id, lesson_id}` for a failed lesson. `409 wrong_stage` (the lesson did not fail), `run_in_progress`, or `not_retryable` (only a lesson build, graph `flow`, can be retried) |
| POST | `/console/runs/{id}/cancel` | The learner's cancel (`LessonService.cancel`): `202 {id, status}`; the lesson is marked failed so it can be retried. `409 run_ended` |
| GET | `/console/providers` | Paged by key: `[{key, kind, api_key_env, api_key_set, base_url, rpm_limit, enabled, models_count, spend_7d}]` |
| PATCH | `/console/providers/{key}` | Only `rpm_limit` (null = no limit), `base_url` and `enabled`; any other field is a `400`. The admin's rules apply (a base URL only for Ollama and OpenAI-compatible providers) |
| GET | `/console/models` | Paged: every model with `provider` (key), `name`, `label`, `enabled`, `api_key_set`, `default_params`, the capability flags, `context_window`, `max_output_tokens`, `rpm_limit`, `input_cost_per_mtok`, `output_cost_per_mtok`, `bound_nodes` (the steps that use it) and `last_probe` (`{at, ok, latency_s, error}` or null) |
| POST | `/console/models` | `201` the new model. Only `provider` and `name` are required; validated like the admin (unique per provider, parameters the provider accepts, reasoning needs a control) |
| PATCH | `/console/models/{id}` | Any field but `provider`, validated the same way |
| DELETE | `/console/models/{id}` | `204`. `409 model_in_use` while a step has it bound (`PROTECT`): the body has `nodes`, the steps, and `detail` names them |
| POST | `/console/models/{id}/probe` | Runs the checks of `manage.py probe_models` for this model now (a plain call, then one for each capability it declares), within 20 seconds, and keeps the result in `last_probe*`. Makes real provider calls. Always `200 {ok, latency_s, error, checks: [{capability, ok, latency_s, detail}]}`: a failing model, a missing key (`capability: "setup"`) and a test that ran out of time are `ok: false` with the first failure as `error` (`latency_s` is that of the plain call, null if it never ran) |
| GET | `/console/nodes` | `{phases: [{phase, nodes}]}` in the order of a lesson (`diagnose`, `author`, `build`, `post`, `onboarding`). Each node: `key, phase, description, optional, output, requires, min_output_tokens, min_context, enabled, reasoning_effort, max_attempts, max_tool_steps, timeout_s, params_override, bindings` in priority order, each `{model (id), model_label, enabled, max_retries, overrides: {params, reasoning_effort}, problems}`. *Required* steps (`optional: false`, from the node spec) cannot be switched off |
| PUT | `/console/nodes/{key}` | Replaces the step's settings and its whole chain atomically (`enabled, reasoning_effort, max_attempts, max_tool_steps, timeout_s, params_override, bindings`: all but the last three required; the order of `bindings` is the priority). Everything is checked before anything is written; a `400` lists the problems under `fields` (`bindings` carries a message for each model: does not exist, switched off, provider key not set, lacks a capability, too small an output or context, parameters the provider rejects, listed twice, or no enabled model at all). Returns the saved node |
| GET | `/console/profiles` | `[{name, label, description, nodes}]` for `default`, `cheap`, `balanced`, `quality` |
| POST | `/console/profiles/{name}/preview` | Saves nothing. `{profile, label, nodes: [{key, changed, current, proposed, problems}], summary: {total, changed, blocked}}`; `proposed` has the shape of a `PUT /console/nodes/{key}` body (with model ids), and `problems` says why it cannot be saved as it is (a model the registry lacks, a provider without a key) |
| GET | `/console/flow-settings` | The `FlowSettings` fields plus `routing_thresholds: {questions_total, foundations_max, mastery_min}`: how many questions the quick check has, the last score sent to the foundations, and the lowest score that can be mastery (`RoutingPolicy.thresholds`) |
| PATCH | `/console/flow-settings` | Any subset of the fields, validated exactly like the admin's form (the same `ModelForm`); applies to lessons started afterwards. A field that does not exist is a `400` |
| GET | `/console/learners?q=` | Paged, newest member first: `[{id, name, email, education_level, grade_or_year, goal, preferred_language, lessons_count, last_active_at, profile_complete, is_staff, joined_at}]` plus `summary: {total, active_7d, profile_complete, staff}` over everyone, whatever `q` (name or email). Read-only; no notes or credentials |
| GET | `/console/audit` | Paged, newest first: `[{id, actor, actor_email, action, target_type, target_id, before, after, changed_fields, created_at}]`. Read-only |

**The run timeline** (`timeline` of `GET /console/runs/{id}`): `[{node, phase, start_offset_s, duration_s, state}]`, oldest start first, from what `GraphRunRecorder` keeps on the run as it streams (`node_status` and `node_timings`: when each graph node first started, when it last finished, and how often the graph ran it again). `start_offset_s` is seconds after the run started (never negative); `duration_s` runs from the step's first start to its last finish, or to now while it is still running. `state` is `failed` (the step failed, or was skipped after failing), `waiting` (a paused run is waiting in this step for the learner, so it has no duration), `retried` (the graph ran the step again after its output failed a check) or `ran`. `phase` (`diagnose`, `author`, `build`, `post`, `other`) comes from the code module that defines the node. Model-level retries and fallbacks are not steps: they are in `model_calls` (`attempt`, `fallback_index`). A run from before timings were kept lists its steps from `node_status` with `start_offset_s` and `duration_s` null.
