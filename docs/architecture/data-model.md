# Data model

Learners and staff share one `User` model. A learner has a login (email and password), a profile, and their own lessons. Staff (`is_staff`) can also sign in to the Django admin and to the staff console (`/console`). There are no other roles, no sharing, and no public lessons. Every lesson-related row is owned through `Lesson.owner`, and every learner-facing query is filtered by the requesting user. The console is the one place that reads across users, and only for staff.

All tables live in one Postgres database: the docker `db` service by default, or Supabase when `SUPABASE_DATABASE_URL` is set (see [local-setup.md](../getting-started/local-setup.md#3-databases-local-postgres-and-supabase)). Django migrations create them. LangGraph checkpoint tables are created by `manage.py setup_checkpointer` (also run by `bootstrap` on every backend start).

Conventions that hold for every table:

- **Primary keys** are UUIDs for `accounts` and `lessons`. The `llm_registry`, `marketing` and `console` tables use auto-incrementing integers.
- **Optional text is an empty string, not NULL.** A text column that may be left blank is stored as `''` (`blank=True` without `null=True`). Only the columns marked "null" below can hold NULL. JSON columns marked "null" are NULL until their stage has run; JSON lists and dicts default to `[]` and `{}`.
- **Choice columns are plain `varchar`.** The allowed values are enforced by Django validation and the serializers, not by a database CHECK constraint.
- **Foreign keys have no `ON DELETE` rule in the database.** Django cascades in code, so a delete done by hand in SQL has to remove children first. What a lesson delete does and does not remove is under [Deleting a lesson](#deleting-a-lesson).

## `accounts`

### `User` (`AUTH_USER_MODEL = "accounts.User"`)

| Field | Type | Notes |
|---|---|---|
| id | UUID | |
| email | email, unique | Login ID (`USERNAME_FIELD`) |
| password | Django hash | |
| name | char | |
| is_active | bool | Default true; a false value blocks sign-in |
| is_staff | bool | Can sign in to the Django admin and the staff console (`/console`) |
| is_superuser | bool | Django's flag; the admin's full permissions |
| date_joined | datetime | |
| terms_accepted_at | datetime, null | When the person confirmed the Terms of Use and Privacy Policy at registration. Null for accounts made before the confirmation existed |
| terms_version | char, blank | `User.TERMS_VERSION` at that moment ("2026-10-25"). Blank for the same older accounts. Nothing compares it with the current version yet, so a newer version does not ask anyone to confirm again |

### `Profile` (one-to-one with User; created on registration and filled in during onboarding)

| Field | Type | Used for |
|---|---|---|
| education_level | enum `school` \| `undergraduate` \| `postgraduate` \| `professional` \| `self_learner` | Depth and vocabulary |
| grade_or_year | char, blank | For example "Class 10" or "2nd year B.Tech" |
| field_of_study | char, blank | Examples and analogies |
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
| user_context | text, blank | Optional extra context from the learner ("for my DSA exam, I know arrays") |
| stage | enum | See the stage table below |
| route | enum `prerequisite` \| `lesson` \| `mastery`, blank | Blank until the diagnostic (or a self-rating) sets it. A learner who aced the quick check and chose the Expert lesson goes from `mastery` to `lesson`, so the lesson has a test |
| entry | enum `diagnostic` \| `self_rating` \| `followup` (\| `quiz_result` in a later phase), default `diagnostic` | How the level is found: the quick check, the learner's own rating, or (a follow-up) what the lesson is for |
| intent | enum `lesson` \| `sheets`, default `lesson` | What was asked for. `sheets` is a lesson that is only study sheets (a cheat sheet, a revision sheet, or both): no pages, no test, no route. Which sheets were asked for is not a column: it is in the start run's `payload["input"]["sheet_kinds"]` (`GET /lessons/{id}` shows it as `sheets_asked`). `Lesson.sheets_only` (a property, not a column) is true for `intent=sheets` and for a lesson that chose the sheets after a perfect quick check |
| origin | enum `direct` \| `recommendation` \| `followup` \| `quiz_result`, default `direct` | Why the lesson was made. **Set and verified by the server**: a client may ask for `direct` or `recommendation`, and a recommendation must name the learner's own graded attempt and a topic it listed (`lessons/origins.py`) |
| recommended_from | JSON, null | For `recommendation`: `{attempt_id, topic}` as verified |
| level_source | enum `diagnostic` \| `self_rating` \| `test_score` \| `quiz_result`, blank | Where `level` came from. Migration 0012 credits `diagnostic` to every lesson that already had a level |
| created_from_lesson | FK to Lesson (self), null, `SET_NULL`, related name `followups` | The lesson a follow-up was made from. Metadata only: a follow-up is a lesson of its own. Deleting the parent clears the link; the follow-up stays |
| followup_level | enum `foundation` \| `advanced`, blank | What kind of follow-up this is. Kept when the parent is deleted. Constraints: a lesson with a parent has a level (`a_followup_has_a_level`; the reverse is not required, because deleting a parent clears the link and not the level), no lesson is its own parent, and **one follow-up of each level for a parent** (`one_followup_per_level`, a partial unique on `(created_from_lesson, followup_level)` where the level is set). The foreign key's own index serves the "does one exist" lookup |
| self_rating_halves | smallint, null | The learner's stars times two (1 to 10; a check constraint refuses others). The API shows stars (`self_rating`, 0.5 to 5) |
| mastery_options | enum `three_sheets` \| `lesson_or_sheets`, default `three_sheets` | Which choice a learner who aced the quick check was shown. The default is what a lesson already waiting at the choice had (migration 0013), so it keeps its three cards; `publish_mastery_options` records `lesson_or_sheets` from now on |
| assessment | JSON, null | `LearnerAssessment`, stamped `level_scheme: 2`: which level names the document uses (see below) |
| prerequisites_to_cover | JSON list | |
| title / level | char | From the plan. `level` is beginner, foundation, proficient or expert (migration 0006 renamed novice … advanced) |
| plan | JSON, null | `LessonPlan`, stamped `level_scheme: 2`, with `quantitative` (whether the topic is mainly calculating). A plan from before the fixed test also has `final_test` (its own mix), which nothing reads now |
| test_blueprint | JSON, null | The fixed `LessonTestBlueprint` of the lesson's test: `{quantitative, total_marks, cells: [{index, type, difficulty, marks}]}` (ten cells, 20 or 18 marks). Written when the plan is saved; null for a lesson made before it, until its first retake |
| pages | JSON, null | `{introduction, core, advanced}` → `PageContent` |
| final_test | JSON, null | `FinalTest`: **the questions of attempt 1**, each with the `question_id` of its row in `Question` (answers kept server-side, see below). Each question has `marks` from `MarksPolicy`, a `difficulty` of easy, basic, standard, difficult or expert, and the fields of its type; a numerical question also has the computed `answer`. Lessons from before the modular parts may hold `medium`/`hard` (migration 0006 renamed them), `code` questions, and `key_points`/`rubric` |
| interactive_plan | JSON, null | |
| code | text, blank | Assembled TSX document |
| code_parts | JSON | The pages' and interactives' TSX the document was assembled from, for targeted runtime repairs |
| code_version | int | Incremented on each runtime repair |
| runtime_repairs | int | Runtime repairs requested so far, counted when requested whether or not they work (capped by `max_auto_runtime_repairs`) |
| warnings | JSON list | Degraded widgets, media fallbacks, minor alignment issues |
| error | text, blank | Readable failure reason |
| config_snapshot | JSON | Resolved model registry used by this lesson's flow |
| settings_snapshot | JSON | `FlowSettings` values used |
| created_at / updated_at | datetime | |

**Stages**

| stage | Meaning | UI shows |
|---|---|---|
| `preparing_diagnostic` | Generating the quizzes (a self-rated lesson leaves this stage at once: it has no quiz) | Spinner with progress |
| `awaiting_diagnostic` | Paused at `interrupt()` | Diagnostic quiz |
| `awaiting_prerequisite` | Paused | Prerequisite quiz |
| `awaiting_choice` | Paused (mastery) | "You know this well" and the choice: an Expert lesson, or the cheat sheet and revision sheet only (three sheet options for a lesson that was already waiting) |
| `generating_material` | Writing the chosen sheet, or the sheets together (also for a lesson that asked for sheets only, from the moment its level is being worked out) | Progress |
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

**Who has sheets, and no versions** (D16). Any ready lesson can have a cheat sheet and a revision sheet made for it; there is no column that says a lesson may, and no version column: a second request for a kind that exists is `409 already_exists`. A sheet made from an existing lesson is a `StudyMaterial` on that lesson (grounded in its content); a sheet from a topic is a `StudyMaterial` on a `Lesson(intent='sheets')`; the sheets of the mastery choice sit on the lesson that took the quick check (grounded in its concepts). One run writes the sheets asked for, and one persist step saves them. A practice sheet that exists is still served, but none can be asked for now (the kind stays so old ones load).

### `QuizAttempt`

| Field | Type | Notes |
|---|---|---|
| quiz | OneToOne Quiz | One attempt per quiz; the diagnostic is not retaken |
| answers | JSON | `{question_id: option_index \| "dont_know"}` |
| result | JSON | `QuizResult` (`graph/grading.py`): `correct`, `total`, `dont_know`, `by_band` (`{band: [correct, total]}`, diagnostic only), `by_concept`, `per_question`, `highest_band_fully_correct`, `consistent` (false when harder bands score clearly better than easier ones) |
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
| file | FileField | Local `MEDIA_ROOT` for now. Swappable to Supabase Storage through `django-storages` later. The file is removed when the row is deleted (`lessons/signals.py`) |
| mime_type / width / height | char / int / int | Sniffed when the file is downloaded; the size in pixels |
| title | char, blank | The source page's title for the image |
| source | enum `wikimedia` \| `openverse` \| `giphy` | |
| source_url / license / attribution | char | Displayed under the figure |
| alt_text / caption | text | |
| verified | bool | Passed `media.verify` |
| created_at | datetime | |

### `Question` (the record of questions)

The record of every question a lesson has asked. It feeds the exclusion list of a retake, holds any question written but not served, and is written **only** by `lessons.bank.QuestionBank`. Questions are immutable: a retake only adds rows, and a question is withdrawn (`retired`), never edited or deleted.

| Field | Type | Notes |
|---|---|---|
| id | UUID | |
| lesson | FK | cascade |
| type / difficulty / concept | char | `mcq`, `msq`, `numerical`, … ; one of the five difficulties; the concept the question tests |
| marks | smallint | From `MarksPolicy`, fixed at creation |
| payload | JSON | The full question **with** its answer key; never sent to a client as it is |
| stem_hash | char(64) | Hash of the normalised question text (`graph.questions.StemHash`). `UniqueConstraint(lesson, stem_hash)`: one row per stem |
| batch | UUID, null | The run that wrote it; none for a question of an old test |
| retired | bool | Withdrawn. **Every question of a lesson's old test is backfilled as retired** (migration 0008), so a retake never repeats an old stem |
| created_at | datetime | |

Indexes on `(lesson, type, difficulty)` and `(lesson, concept)`.

### `TestSubmission` (an attempt)

The model, table and URL names stay from when a lesson had one submission; in prose and in the app it is an **attempt**.

| Field | Type | Notes |
|---|---|---|
| lesson | FK | |
| attempt_no | smallint | Per lesson, from 1. `UniqueConstraint(lesson, attempt_no)` |
| questions | JSON | The snapshot of the questions served, answer keys included. What makes the attempt immutable and gradable whatever happens to the record later. Empty while `generating` |
| answers | JSON | `{question_id: answer}`. A question that has an answer is **locked**: `PUT …/answers/{qid}` is forward-only on the server |
| result | JSON, null | The `ScoreCard` (`graph/grading.py`): score, per-question marks, feedback and solution (for a model-graded answer also its `criteria` with what each earned), topics to revisit. For a legacy attempt with written answers, at first only what could be marked at once (`complete: false`) |
| status | enum | `generating` (a retake waits for its questions) \| `in_progress` \| `grading` (legacy attempts with open-ended questions only) \| `graded` \| `failed` (grading) |
| error | text | Why grading failed (blank otherwise) |
| started_at | datetime | When the attempt started; for a retake, when its questions were ready |
| submitted_at / graded_at | datetime, null | `submitted_at` is null while the attempt is open |
| awarded / available | smallint, null | Whole marks, filled when graded: trends and bands need no JSON |
| band | char | `fail`, `normal` or `excellent` once graded (blank before) |
| duration_s | int, null | Measured by the server, `started_at` to `submitted_at` |
| followup | JSON, null | The offer decided with the band: `{kind: foundation \| advanced \| inline_suggestion, action: generate \| revisit \| open \| revisit_or_related, lesson_id}`, or null (`FollowupPolicy`, §4.21 of design.md). Decided when the attempt is graded and never changed |
| all_blank | bool | Every answer was blank: stored and scored 0, but not counted toward the Foundation offer (phase 9.4) |

**One open attempt at a time**: a partial unique constraint on `lesson` where `status in ('generating', 'in_progress')`, so a double click cannot draw two sets or authorize twice.

**Immutability.** `TestSubmission.seal()` is the only way out of `in_progress`; it stores the answers, the result and everything that follows from them in one conditional update, and a second call changes nothing. The answer endpoint is the only other writer of `answers`, and the retake graph the only writer of `questions` (once, while the attempt is `generating`). A test scans the code for any other update of those two fields.

**Attempt 1** is part of the lesson: it starts at once, with a copy of `Lesson.final_test` as its snapshot. **Attempt 2 and later** always generate a fresh set (the `question_bank` graph). A lesson made before the fixed test can retake too: its attempt 1 keeps its old questions and total, and the trend compares percents.

Migrations: `0007` adds the table and columns and the constraints below; `0008` makes every existing submission attempt 1 (questions copied from the lesson's old test, `started_at` = `submitted_at`, marks and band from its card when graded) and writes every question of every old test as a retired `Question`; `0009` adds the `question_bank` graph and the `retake` trigger to `GraphRun`. The one-submission constraint `UniqueConstraint(lesson)` was **dropped last** (`0010`), in the release that ships the retest screens; undoing it keeps the first attempt of each lesson.

### `LessonVersion`

This is a snapshot of `code`, `code_parts` and `code_version` taken before each runtime repair and each restore, for rollback, with a `reason` (a short sentence saying which) and `created_at`. `(lesson, code_version)` is unique; the current version has no row. The headless render check's own repairs, made while a lesson is still being built, do not create a version.

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
| payload | JSON | What the run was started with. A resume after a quiz is `{"resume": <attempt id>}` and after the sheet choice `{"resume": <kind>}`; other graphs get `{"input": {...}}` (grading: `{"submission_id"}`; runtime repair: `{"repair_error", "expected_code_version"}`; more sheets: `{"sheet_kinds": [...], "extra_material": true}`; the start run of a lesson that asked for sheets: `{"sheet_kinds": [...]}`). A retry carries the answer the stopped run was about to give. A stopped flow run also carries `stopped_in`: the stage Retry puts the lesson back in, or `""` when the thread was not at a question (the lesson then stays `failed` until the first node that runs moves it) |
| celery_task_id | char | |
| error | text, blank | |
| created_at | datetime | |
| started_at / finished_at | datetime, null | |

### `FlowSettings` (singleton, edited in the admin)

| Setting | Default |
|---|---|
| diagnostic_questions_per_band | 2 (5 bands, so 10 questions) |
| prerequisite_question_count | 5 |
| prereq_trigger_max_correct | 2 |
| mastery_requires_all_correct | true |
| final_test_min / final_test_max | 10 / 15 (retired: the test is fixed at ten questions in code; the columns stay for old snapshots and are not read, edited or shown) |
| max_interactives_per_page | 3 |
| alignment_min_score | 3 (out of 5) |
| alignment_max_rounds | 2 |
| render_check_max_rounds | 2 |
| max_auto_runtime_repairs | 2 |
| band_fail_below / band_excellent_above | 30 / 90 (percent: under the first is a Fail, over the second Excellent; the first must be below the second) |
| question_batch_size | 5 (5 to 10: questions written per model call) |
| batch_max_long / batch_max_short | 1 / 2 (written answers per batch; off when only short or long answers were asked) |
| retakes_per_day | 3 (per lesson, in 24 hours; attempt 1 does not count) |
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

The tables `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` and `checkpoint_migrations` are created by `PostgresSaver.setup()` (`manage.py setup_checkpointer`) in the same database. They are not Django models. Treat them as internal. A flow's `thread_id` is the lesson id; the `grade_test`, `study_material` and `runtime_repair` graphs use `<lesson id>:<run id>`. The checkpoints hold the generated quizzes with their answer keys, the learner's profile and topic, and the submitted test answers, so they are as sensitive as the lesson rows. If you use Supabase, enable row-level security on them (the lock-down script is still on the roadmap).

## `llm_registry`

`Provider`, `LLMModel`, `NodeConfig` and `NodeModelBinding` are described in [model-registry.md](model-registry.md). `ModelCall` is the log of every model attempt:

| Field | Type | Notes |
|---|---|---|
| id | integer | |
| lesson_id / run_id / quiz_id | UUID, null, indexed | **Plain columns, not foreign keys**, so a call can outlive a deleted run. `quiz_id` is for the quick quiz a call was made for (phase 9.6); it is empty today. A lesson's calls are deleted with the lesson (see [Deleting a lesson](#deleting-a-lesson)) |
| node_key / provider_key / model_name | char | The step and the model that answered |
| attempt / fallback_index | smallint | Which retry, and how far down the fallback chain |
| status | enum | `ok`, `retryable_error`, `fatal_error` or `invalid_output` |
| error | text, blank | The failure text. Credentials are scrubbed (`llm_registry/redaction.py`), but nothing else is, so it can carry the model's own output, for example a rejected quiz with its answer key |
| latency_ms / rate_limit_wait_ms | int | Latency includes any wait for a rate-limit window |
| input_tokens / output_tokens / reasoning_tokens | int, null | Null when the provider did not report them, and on failed calls |
| tool_calls | smallint | |
| cost | decimal, null | Null while the model has no price set (`input_cost_per_mtok`, `output_cost_per_mtok`), which makes the console show 0 spend |
| created_at | datetime, indexed | Also indexed with `model_name` and with `node_key` for the console's usage page |

## Level names and difficulties (migration 0006)

Levels were novice, beginner, intermediate, advanced; they are now **beginner, foundation, proficient, expert**, and "beginner" is in both with different meanings. A stored document therefore says which it uses: `assessment` and `plan` carry `level_scheme: 2` when they use the new names, and `graph.levels.LevelScheme.level_of` reads one with `Level.parse` if it has the stamp and with `Level.parse_legacy` (old names by position) if it does not. The same marker is on the flow state of a new lesson. Migration `lessons/0006_level_and_difficulty_names` rewrites every lesson row once (`Lesson.level`, `assessment`, `plan`, and the difficulties below) and stamps the documents; **graph checkpoints are not rewritten**, and a checkpoint without the stamp is read as legacy. Undoing the migration is lossy for the two new difficulties (basic reads as easy, expert as hard).

**Stage moves added with sheets from a topic.** `preparing_diagnostic → generating_material` (a rated lesson that asked for sheets goes straight to writing them) and `awaiting_diagnostic → generating_material` (a quick check that asked for sheets goes from the graded score to the assessment and the sheets, whatever the score).

**Stage moves added with self-rating.** `preparing_diagnostic → generating_lesson` (a self-rated lesson has no quiz) and `awaiting_choice → generating_lesson` (the Expert lesson), next to the existing `awaiting_choice → generating_material` (sheets).

Difficulties were easy, medium, hard; they are now **easy, basic, standard, difficult, expert** (medium became standard, hard became difficult). The migration renames every `difficulty` value and every `difficulty_mix` in `Lesson.final_test`, `Lesson.plan` and `StudyMaterial.content`; a test lists every JSON column of the app and fails when one is neither rewritten nor known to hold neither name. `ModelCall.quiz_id`, `GraphRun.subject` and the rest of phase 9 are described in the plan.

## Deleting a lesson

`DELETE /api/lessons/{id}` (`LessonService.delete`) cancels any active run, then deletes the `Lesson` row. Django cascades to its `Quiz`, `QuizAttempt`, `StudyMaterial`, `MediaAsset` (the files go with them), `LessonVersion`, `TestSubmission` (every attempt), `Question` and `GraphRun` rows.

Two more things hold learner data and are not reached by the cascade, so `LessonErasure` (`lessons/erasure.py`) removes them first, before the lesson row:

- the LangGraph checkpoint rows for the lesson's threads: the flow thread `<lesson id>` and one `<lesson id>:<run id>` for each small graph run (see above);
- the `ModelCall` rows with the lesson's `lesson_id` (they are not linked by a foreign key).

If erasing fails, the lesson stays and the delete can be repeated. A step that was still writing a checkpoint when the run was cancelled can leave one more behind in the instant before it notices.

There is no self-service account deletion: the Privacy page tells people to ask by email. **Removing a user by hand still leaves both sets of rows behind** (open work in [roadmap.md](../process/roadmap.md)).

## Access rules

- Every lessons endpoint filters by `owner=request.user`. Another user's lesson ID returns `404`, not `403`.
- Every `/api/console` endpoint requires `User.is_staff`; anyone else, signed in or not, gets a `404`.
- Quiz answers and final-test answers stay server-side until the learner submits.
- `MediaAsset` files are served through **signed, expiring URLs** (`/api/media/{asset_id}?exp=…&sig=…`, HMAC with `DJANGO_SECRET_KEY`). The URLs are generated when the lesson detail is fetched and passed into the sandbox as `LESSON.media`. Cookies can't be used here: the sandboxed iframe has an opaque origin, so the browser does not send the session cookie on its image requests.
