# Data model

There is **one kind of user**. Each user has a login (email and password), a profile, and their own lessons. There are no roles, no sharing, and no public lessons. Every lesson-related row is owned through `Lesson.owner`, and every query is filtered by the requesting user.

All tables live in the Supabase Postgres `public` schema and are created by Django migrations. LangGraph checkpoint tables are created by `manage.py setup_checkpointer` (also run by `bootstrap` on every backend start). Primary keys are UUIDs.

## `accounts`

### `User` (`AUTH_USER_MODEL = "accounts.User"`)

| Field | Type | Notes |
|---|---|---|
| id | UUID | |
| email | email, unique | Login ID (`USERNAME_FIELD`) |
| password | Django hash | |
| name | char | |
| is_staff / is_superuser | bool | Admin access to the model registry and settings |
| date_joined | datetime | |

### `Profile` (one-to-one with User; created on registration and filled in during onboarding)

| Field | Type | Used for |
|---|---|---|
| education_level | enum `school` \| `undergraduate` \| `postgraduate` \| `professional` \| `self_learner` | Depth and vocabulary |
| grade_or_year | char, null | For example "Class 10" or "2nd year B.Tech" |
| field_of_study | char, null | Examples and analogies |
| preferred_language | enum `en` \| `hi` \| `es` \| `fr` \| `de`, default `en` | Language of generated content, and of the suggested first topics |
| learning_preference | enum `visual` \| `reading` \| `hands_on` \| `mixed` | How many interactives, and which kinds |
| goal | enum `exam_prep` \| `deep_understanding` \| `quick_overview` \| `interview_prep` | Tone and test style |
| notes | text, at most 2000 characters | Anything else the learner wants the tutor to know |
| updated_at | datetime | |

The graph turns this into `LearnerProfile` in `load_context`.

## `marketing`

### `DemoQuestion` (the landing page's try-it question bank; curated in the Django admin)

| Field | Type | Used for |
|---|---|---|
| subject | char | "Physics", "Personal finance"...; shown in the card's label and a filter in the admin |
| level_label | char | Who it is pitched at: "Class 8", "College", "Working" |
| band | smallint 1–5 | Difficulty: 1 Basics, 2 Easy, 3 Medium, 4 Hard, 5 Expert |
| question | char | Short: two lines in the card |
| options | JSON list of exactly 3 different texts | |
| correct_index | smallint 0–2 | The right option |
| outcome_right, outcome_wrong | JSON `{level 1–5, level_label, lesson_start}` | The "Your starting point" card after a right answer, and after a wrong one or "I don't know"; a right answer never leaves the learner lower |
| is_active | bool | Only active questions are served |
| created_at | datetime | |

`clean()` enforces all of this, so the admin refuses a broken question. Migration `marketing.0002` seeds 25 questions across 13 subjects, Class 6 to working, all five bands. The picker caches the active ids for 10 minutes (`LANDING_DEMO_IDS_TTL_S`) and clears them when a question is saved or deleted.

## `lessons`

### `Lesson`

A lesson is a learner's request to learn one topic, from the diagnostic quiz through to the finished lesson or study sheet.

| Field | Type | Notes |
|---|---|---|
| id | UUID | Also the LangGraph `thread_id` |
| owner | FK User | |
| topic | char | "Binary search" |
| user_context | text, null | Optional extra context from the learner ("for my DSA exam, I know arrays") |
| stage | enum | See the stage table below |
| route | enum `prerequisite` \| `lesson` \| `mastery`, null | Set after the diagnostic |
| assessment | JSON, null | `LearnerAssessment` |
| prerequisites_to_cover | JSON list | |
| title / level | char | From the plan |
| plan | JSON, null | `LessonPlan` |
| pages | JSON, null | `{introduction, core, advanced}` → `PageContent` |
| final_test | JSON, null | `FinalTest` (answers kept server-side, see below) |
| interactive_plan | JSON, null | |
| code | text, null | Assembled TSX document |
| code_parts | JSON | The pages' and interactives' TSX the document was assembled from, for targeted runtime repairs |
| code_version | int | Incremented on each runtime repair |
| runtime_repairs | int | Runtime repairs requested so far, counted when requested whether or not they work (capped by `max_auto_runtime_repairs`) |
| warnings | JSON list | Degraded widgets, media fallbacks, minor alignment issues |
| error | text, null | Readable failure reason |
| config_snapshot | JSON | Resolved model registry used by this lesson's flow |
| settings_snapshot | JSON | `FlowSettings` values used |
| created_at / updated_at | datetime | |

**Stages**

| stage | Meaning | UI shows |
|---|---|---|
| `preparing_diagnostic` | Generating the quizzes | Spinner with progress |
| `awaiting_diagnostic` | Paused at `interrupt()` | Diagnostic quiz |
| `awaiting_prerequisite` | Paused | Prerequisite quiz |
| `awaiting_choice` | Paused (mastery) | "You know this well" and three sheet options |
| `generating_material` | Writing the chosen sheet | Progress |
| `generating_lesson` | Stages B and C | Pipeline progress |
| `ready` | Done | Lesson viewer or sheet viewer |
| `failed` | Unrecoverable error | Error and **Retry** (resumes from the last checkpoint) |

### `Quiz`

| Field | Type | Notes |
|---|---|---|
| id | UUID | |
| lesson | FK | |
| kind | enum `diagnostic` \| `prerequisite` | |
| questions | JSON | Full questions **including** `correct_index` and `explanation`. Never serialized to the client before submission. |
| prerequisites | JSON, null | Prerequisite quiz only |
| created_at | datetime | |

`unique_together = (lesson, kind)`

### `QuizAttempt`

| Field | Type | Notes |
|---|---|---|
| quiz | OneToOne Quiz | One attempt per quiz; the diagnostic is not retaken |
| answers | JSON | `{question_id: option_index \| "dont_know"}` |
| result | JSON | `QuizResult`: correct, by_band, by_concept, dont_know_count, consistency |
| submitted_at | datetime | |

### `StudyMaterial`

| Field | Type | Notes |
|---|---|---|
| lesson | FK | |
| kind | enum `cheat_sheet` \| `revision_sheet` \| `practice_sheet` | |
| content | JSON | Kind-specific schema, rendered by a fixed template |
| created_at | datetime | |

`unique_together = (lesson, kind)`

### `MediaAsset`

| Field | Type | Notes |
|---|---|---|
| id | UUID | Referenced from lesson code as `<Figure asset="...">` |
| lesson | FK | |
| spec_id | char | Which `InteractiveSpec` it fills |
| kind | enum `image` \| `gif` | |
| file | FileField | Local `MEDIA_ROOT` for now. Swappable to Supabase Storage through `django-storages` later. |
| source | enum `wikimedia` \| `openverse` \| `giphy` | |
| source_url / license / attribution | char | Displayed under the figure |
| alt_text / caption | text | |
| verified | bool | Passed `media.verify` |

### `TestSubmission`

| Field | Type | Notes |
|---|---|---|
| lesson | FK | |
| answers | JSON | `{question_id: answer}` |
| result | JSON, null | The `ScoreCard` (`graph/grading.py`): score, per-question marks, feedback and solution, topics to revisit. At first only what could be marked at once (`complete: false`) |
| status | enum `grading` \| `graded` \| `failed` | |
| error | text | Why grading failed (blank otherwise) |
| submitted_at / graded_at | datetime | |

A lesson has at most one submission (`UniqueConstraint(lesson)`): the test is taken once, and a failed grading is run again on the stored `answers`. The migration `0003` kept the most recent graded submission per lesson (else the most recent) and deleted the rest before the constraint of `0004` was added.

### `LessonVersion`

This is a snapshot of `code`, `code_parts` and `code_version` taken before each runtime repair and each restore, for rollback. `(lesson, code_version)` is unique; the current version has no row.

### `GraphRun`

There is one row per Celery execution segment of any graph, for example start, each resume, a repair, or grading. It powers progress streaming and debugging.

| Field | Type | Notes |
|---|---|---|
| id | UUID | SSE channel `run:{id}:events` |
| lesson | FK | |
| graph | enum `flow` \| `study_material` \| `runtime_repair` \| `grade_test` | |
| trigger | enum `start` \| `resume_diagnostic` \| `resume_prerequisite` \| `resume_choice` \| `retry` \| `repair` \| `grade` \| `extra_material` | |
| status | enum `queued` \| `running` \| `paused` \| `succeeded` \| `failed` \| `cancelled` | `paused` = ended at an `interrupt()` |
| node_status | JSON | `{node: pending \| running \| done \| retrying \| degraded \| failed}` |
| node_timings | JSON | `{node: {started_at, finished_at, retries}}`, kept by `GraphRunRecorder` next to `node_status`: the node's first start, its latest finish (null while it runs or waits) and how often the graph ran it again. Runs from before it existed have `{}`. The console's timeline reads it |
| payload | JSON | The resume value (`{"resume": attempt_id}`) or the requested sheet kind |
| celery_task_id | char | |
| error | text, null | |
| started_at / finished_at | datetime | |

### `FlowSettings` (singleton, edited in the admin)

| Setting | Default |
|---|---|
| diagnostic_questions_per_band | 2 (5 bands, so 10 questions) |
| prerequisite_question_count | 5 |
| prereq_trigger_max_correct | 2 |
| mastery_requires_all_correct | true |
| final_test_min / final_test_max | 10 / 15 |
| max_interactives_per_page | 3 |
| alignment_min_score | 3 (out of 5) |
| alignment_max_rounds | 2 |
| render_check_max_rounds | 2 |
| max_auto_runtime_repairs | 2 |
| media_sources | `["wikimedia", "openverse"]` |
| allowed_media_licenses | `["cc0", "pdm", "cc-by", "cc-by-sa"]` |

## `console`

### `AuditEntry` (the change log of the staff console; read-only everywhere, including the admin)

| Field | Type | Notes |
|---|---|---|
| actor | FK User, null | `SET_NULL`: the entry outlives the account |
| actor_email | email | The address at the time |
| action | char | `run.retry`, `run.cancel`, `provider.update`, `model.create` \| `update` \| `delete` \| `probe`, `node.update`, `flow_settings.update` |
| target_type / target_id | char | `run`, `provider`, `model`, `node` or `flow_settings`; the run id, provider key, model id, node key or `1` |
| before / after | JSON, null | The target as it was and as it became (what the console API shows, never a secret; null for a creation / a deletion) |
| created_at | datetime | |

Written by `console.audit.AuditTrail` in the same transaction as the change.

## LangGraph checkpoint tables

These are created by `PostgresSaver.setup()` (`manage.py setup_checkpointer`) in the same database. They are not Django models. Treat them as internal and include them in the RLS lock-down script.

## Access rules

- Every lessons endpoint filters by `owner=request.user`. Another user's lesson ID returns `404`, not `403`.
- Every `/api/console` endpoint requires `User.is_staff`; anyone else, signed in or not, gets a `404`.
- Quiz answers and final-test answers stay server-side until the learner submits.
- `MediaAsset` files are served through **signed, expiring URLs** (`/api/media/{asset_id}?exp=…&sig=…`, HMAC with `DJANGO_SECRET_KEY`). The URLs are generated when the lesson detail is fetched and passed into the sandbox as `LESSON.media`. Cookies can't be used here: the sandboxed iframe has an opaque origin, so the browser does not send the session cookie on its image requests.
