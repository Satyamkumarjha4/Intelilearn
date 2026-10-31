"""A lesson is one learner's request to learn one topic: diagnostic quiz → lesson or study sheet.

Every lesson-scoped row hangs off `Lesson.owner`; the API always filters by the requesting user.
The LangGraph thread for a lesson uses `Lesson.id` as its thread_id (checkpoints live in Postgres).
"""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .errors import AttemptSealed
from .stages import (  # noqa: F401  (re-exported)
    Entry,
    FollowupLevel,
    IllegalTransition,
    Intent,
    LevelSource,
    MasteryOptions,
    MaterialKind,
    Origin,
    Route,
    Stage,
    StageTransitions,
)
from .subjects import RunSubject


class LessonQuerySet(models.QuerySet):
    """Ownership lives here, so a view that forgets to filter cannot start from `Lesson.objects.all()` by habit."""

    def owned_by(self, user) -> "LessonQuerySet":
        return self.filter(owner=user)

    def active(self) -> "LessonQuerySet":
        """Lessons still being worked on (not ready, not failed)."""
        return self.exclude(stage__in=[Stage.READY, Stage.FAILED])


class Lesson(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lessons")
    topic = models.CharField(max_length=200)
    user_context = models.TextField(blank=True)
    stage = models.CharField(max_length=30, choices=Stage.choices, default=Stage.PREPARING_DIAGNOSTIC)
    route = models.CharField(max_length=20, choices=Route.choices, blank=True)
    # How the lesson came about (docs/architecture/data-model.md). `entry` says how the level was found, `origin`
    # why the lesson was made; the server sets and verifies `origin`, so a client cannot claim one.
    intent = models.CharField(max_length=10, choices=Intent.choices, default=Intent.LESSON)
    origin = models.CharField(max_length=20, choices=Origin.choices, default=Origin.DIRECT)
    recommended_from = models.JSONField(null=True, blank=True)  # {attempt_id, topic} for a recommended lesson
    entry = models.CharField(max_length=20, choices=Entry.choices, default=Entry.DIAGNOSTIC)
    level_source = models.CharField(max_length=20, choices=LevelSource.choices, blank=True)
    self_rating_halves = models.PositiveSmallIntegerField(null=True, blank=True)  # stars times two, 1 to 10
    # A follow-up is a lesson of its own, linked to the one it came from by metadata only. The parent can be deleted and
    # the follow-up stays (the link goes, what it is for does not).
    created_from_lesson = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="followups"
    )
    followup_level = models.CharField(max_length=10, choices=FollowupLevel.choices, blank=True)
    # What the mastery choice offered, set when it is published; the old three-sheet choice is what a row from before
    # the Expert lesson has, so the page shows those learners the cards they were waiting at.
    mastery_options = models.CharField(
        max_length=20, choices=MasteryOptions.choices, default=MasteryOptions.THREE_SHEETS
    )

    # Stage A
    assessment = models.JSONField(null=True, blank=True)  # LearnerAssessment
    prerequisites_to_cover = models.JSONField(default=list, blank=True)
    # Stage B
    title = models.CharField(max_length=200, blank=True)
    level = models.CharField(max_length=20, blank=True)
    plan = models.JSONField(null=True, blank=True)  # LessonPlan
    pages = models.JSONField(null=True, blank=True)  # {introduction, core, advanced} → PageContent
    final_test = models.JSONField(null=True, blank=True)  # FinalTest, answers included: never sent as-is
    # The fixed LessonTestBlueprint (cells and total marks), written when the plan is saved. Null for a lesson made
    # before it, until its first retake.
    test_blueprint = models.JSONField(null=True, blank=True)
    interactive_plan = models.JSONField(null=True, blank=True)
    # Stage C
    code = models.TextField(blank=True)  # the assembled TSX document
    code_parts = models.JSONField(default=dict, blank=True)  # {pages: {key: tsx}, interactives: {name: tsx}}
    code_version = models.PositiveIntegerField(default=0)
    runtime_repairs = models.PositiveIntegerField(default=0)

    warnings = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)
    config_snapshot = models.JSONField(default=dict, blank=True)  # resolved model registry used by this flow
    settings_snapshot = models.JSONField(default=dict, blank=True)  # FlowSettings used by this flow
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = LessonQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["owner", "-created_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(self_rating_halves__isnull=True)
                | models.Q(self_rating_halves__gte=1, self_rating_halves__lte=10),
                name="self_rating_is_one_to_ten_halves",
            ),
            # A lesson made from another says what kind of follow-up it is. (The reverse is not required: deleting the
            # parent clears the link and the follow-up keeps its level.) And no lesson is its own parent.
            models.CheckConstraint(
                condition=models.Q(created_from_lesson__isnull=True) | ~models.Q(followup_level=""),
                name="a_followup_has_a_level",
            ),
            models.CheckConstraint(
                condition=~models.Q(created_from_lesson=models.F("id")), name="a_lesson_is_not_its_own_parent"
            ),
            # "Never a second Foundation lesson", even when two requests race.
            models.UniqueConstraint(
                fields=["created_from_lesson", "followup_level"],
                condition=models.Q(followup_level__gt=""),
                name="one_followup_per_level",
            ),
        ]

    def __str__(self):
        return f"{self.topic} ({self.get_stage_display()})"

    @property
    def sheets_only(self) -> bool:
        """The lesson is study sheets and nothing else: no pages and no test. It asked for sheets, or it chose them
        after a perfect quick check (a lesson still waiting at that choice has not decided)."""
        return self.intent == Intent.SHEETS or (self.route == Route.MASTERY and self.stage != Stage.AWAITING_CHOICE)

    def advance_to(self, stage: Stage, **fields) -> None:
        """Move to `stage` (and set `fields`) if that is a legal move from the *stored* stage.

        Judged against the database, not this instance, because graph nodes and API calls run in different
        processes. Clears any earlier error.
        """
        current = Lesson.objects.values_list("stage", flat=True).get(pk=self.pk)
        if not StageTransitions().allowed(current, stage):
            raise IllegalTransition(f"A lesson cannot go from {current} to {stage}.")
        self.record(stage=stage, error="", **fields)

    def fail(self, error: str) -> None:
        """Mark the lesson failed with a readable reason. A lesson that is already ready stays usable."""
        current = Lesson.objects.values_list("stage", flat=True).get(pk=self.pk)
        if StageTransitions().allowed(current, Stage.FAILED):
            self.record(stage=Stage.FAILED, error=error)

    def record(self, **fields) -> None:
        """Write only these fields (never the whole row, so a concurrent update elsewhere is not overwritten)."""
        Lesson.objects.filter(pk=self.pk).update(updated_at=timezone.now(), **fields)
        for name, value in fields.items():
            setattr(self, name, value)


class Quiz(models.Model):
    class Kind(models.TextChoices):
        DIAGNOSTIC = "diagnostic", "Diagnostic"
        PREREQUISITE = "prerequisite", "Prerequisite"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="quizzes")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    # Full questions INCLUDING correct_index and explanation: never serialised to the learner before the attempt.
    questions = models.JSONField()
    prerequisites = models.JSONField(null=True, blank=True)  # prerequisite quiz only
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["lesson", "kind"], name="unique_quiz_kind_per_lesson")]
        verbose_name_plural = "quizzes"

    def __str__(self):
        return f"{self.get_kind_display()} quiz for {self.lesson.topic}"

    PUBLIC_FIELDS = ("id", "band", "question", "options")

    def public_questions(self) -> list[dict]:
        """The only way questions leave the server before the attempt: no answer, explanation or concept."""
        return [{key: q[key] for key in self.PUBLIC_FIELDS if key in q} for q in self.questions]


class QuizAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    quiz = models.OneToOneField(Quiz, on_delete=models.CASCADE, related_name="attempt")
    answers = models.JSONField()  # {question_id: option_index | "dont_know"}
    result = models.JSONField()  # QuizResult (graph/grading.py)
    submitted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Attempt on {self.quiz}"


class StudyMaterial(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="materials")
    kind = models.CharField(max_length=20, choices=MaterialKind.choices)
    content = models.JSONField()  # CheatSheet / RevisionSheet / PracticeSheet
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [models.UniqueConstraint(fields=["lesson", "kind"], name="unique_material_kind_per_lesson")]

    def __str__(self):
        return f"{self.get_kind_display()} for {self.lesson.topic}"


def _media_path(instance, filename):
    return f"lesson-media/{instance.lesson_id}/{filename}"


class MediaAsset(models.Model):
    class Kind(models.TextChoices):
        IMAGE = "image", "Image"
        GIF = "gif", "GIF"

    class Source(models.TextChoices):
        WIKIMEDIA = "wikimedia", "Wikimedia Commons"
        OPENVERSE = "openverse", "Openverse"
        GIPHY = "giphy", "Giphy"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # <Figure asset="…">
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="media")
    spec_id = models.CharField(max_length=80)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    file = models.FileField(upload_to=_media_path, max_length=300)
    mime_type = models.CharField(max_length=40)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    source = models.CharField(max_length=20, choices=Source.choices)
    source_url = models.URLField(max_length=1000, blank=True)  # the page it came from
    title = models.CharField(max_length=300, blank=True)
    license = models.CharField(max_length=40, blank=True)
    attribution = models.CharField(max_length=500, blank=True)
    alt_text = models.TextField(blank=True)
    caption = models.TextField(blank=True)
    verified = models.BooleanField(default=False, help_text="Passed the media.verify vision check.")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_kind_display()} {self.spec_id} ({self.source})"


class LessonVersion(models.Model):
    """The lesson code as it was before a runtime repair or restore, so it can be rolled back."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="versions")
    code_version = models.PositiveIntegerField()
    code = models.TextField()
    code_parts = models.JSONField(default=dict, blank=True)
    reason = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-code_version"]
        constraints = [models.UniqueConstraint(fields=["lesson", "code_version"], name="unique_lesson_version")]

    def __str__(self):
        return f"{self.lesson.topic} v{self.code_version}"


class Question(models.Model):
    """The record of the questions a lesson has asked (docs/architecture/data-model.md). Questions are immutable once
    created: a retake only adds rows. A row feeds the exclusion list for the next retake and holds any question that was
    written but not served. Only `lessons.bank.QuestionBank` writes here."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="questions")
    type = models.CharField(max_length=20)  # mcq, msq, numerical, short_answer, long_answer (or a legacy code)
    difficulty = models.CharField(max_length=20)
    concept = models.CharField(max_length=200, blank=True)
    marks = models.PositiveSmallIntegerField()  # from MarksPolicy, fixed at creation
    payload = models.JSONField()  # the full question with its answer key: never sent to a client as it is
    stem_hash = models.CharField(max_length=64)  # of the normalised question text (graph.questions.StemHash)
    batch = models.UUIDField(null=True, blank=True)  # the generation that made it; none for a legacy question
    retired = models.BooleanField(default=False, help_text="Withdrawn without deleting, so past attempts stay valid.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [models.UniqueConstraint(fields=["lesson", "stem_hash"], name="unique_question_stem_per_lesson")]
        indexes = [
            models.Index(fields=["lesson", "type", "difficulty"], name="question_lesson_cell"),
            models.Index(fields=["lesson", "concept"], name="question_lesson_concept"),
        ]

    def __str__(self):
        return f"{self.type} question of {self.lesson.topic}"


class TestSubmission(models.Model):
    """One attempt at the lesson's test. The model, table and URL names stay from when a lesson had a single
    submission; in prose and in the app it is an attempt.

    A lesson can have many, numbered from 1, and at most one is open (`generating` while a retake's questions are being
    written, then `in_progress`). `questions` is the snapshot of what was served, answer keys included, which is what
    makes an attempt immutable and gradable whatever happens to the record later. Once the attempt leaves `in_progress`
    its `answers` and `questions` never change: `seal()` is the only way out. `result` is the `ScoreCard`
    (graph/grading.py): complete at once for an objective attempt, and when the `grade_test` graph has graded the
    open-ended answers for a legacy one.
    """

    __test__ = False  # not a pytest test class, whatever its name looks like

    class Status(models.TextChoices):
        GENERATING = "generating", "Preparing questions"
        IN_PROGRESS = "in_progress", "In progress"
        GRADING = "grading", "Grading"  # legacy attempts with open-ended questions only
        GRADED = "graded", "Graded"
        FAILED = "failed", "Grading failed"

    OPEN = (Status.GENERATING, Status.IN_PROGRESS)
    SEALED = (Status.GRADING, Status.GRADED, Status.FAILED)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="submissions")
    attempt_no = models.PositiveSmallIntegerField(default=1)  # per lesson, from 1
    questions = models.JSONField(default=list, blank=True)  # the snapshot of the questions served in this attempt
    answers = models.JSONField(default=dict)  # {question_id: answer}; an answered question is locked
    result = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.IN_PROGRESS)
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    submitted_at = models.DateTimeField(null=True, blank=True)  # none while the attempt is open
    graded_at = models.DateTimeField(null=True, blank=True)
    awarded = models.PositiveSmallIntegerField(null=True, blank=True)  # filled when graded, so trends are cheap
    available = models.PositiveSmallIntegerField(null=True, blank=True)
    band = models.CharField(max_length=10, blank=True)  # fail, normal or excellent, once graded
    duration_s = models.PositiveIntegerField(null=True, blank=True)  # server-measured, started_at to submitted_at
    followup = models.JSONField(null=True, blank=True)  # the offer decided with the band (none until phase 9.4)
    all_blank = models.BooleanField(default=False, help_text="Every answer was blank. Stored, scores 0, no offer.")

    class Meta:
        ordering = ["-attempt_no"]
        constraints = [
            models.UniqueConstraint(fields=["lesson", "attempt_no"], name="unique_attempt_no_per_lesson"),
            models.UniqueConstraint(
                fields=["lesson"],
                condition=models.Q(status__in=["generating", "in_progress"]),
                name="one_open_attempt_per_lesson",
            ),
        ]

    def __str__(self):
        return f"Attempt {self.attempt_no} of {self.lesson.topic} ({self.get_status_display()})"

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN

    def seal(
        self, *, answers: dict, status: str, result: dict, band: str, followup: dict | None, all_blank: bool, now
    ) -> None:
        """Close an attempt that is in progress: its answers are final, and so is what they scored (or, for a legacy
        attempt with open-ended answers, the part of it that could be marked at once). The only way out of
        `in_progress`; the conditional update makes a second call, or a call on a closed attempt, do nothing."""
        score = result["score"]
        sealed = TestSubmission.objects.filter(pk=self.pk, status=self.Status.IN_PROGRESS).update(
            answers=answers,
            status=status,
            result=result,
            awarded=score["awarded"] if status == self.Status.GRADED else None,
            available=score["available"] if status == self.Status.GRADED else None,
            band=band,
            followup=followup,
            all_blank=all_blank,
            submitted_at=now,
            graded_at=now if status == self.Status.GRADED else None,
            duration_s=max(0, int((now - self.started_at).total_seconds())),
        )
        if not sealed:
            raise AttemptSealed()
        self.refresh_from_db()


class GraphRunQuerySet(models.QuerySet):
    """The ways to find runs without naming the column of the thing they belong to (`GraphRun.SUBJECT_FIELDS`)."""

    def for_subject(self, subject: RunSubject) -> "GraphRunQuerySet":
        try:
            field = GraphRun.SUBJECT_FIELDS[type(subject)]
        except KeyError:
            raise TypeError(f"{type(subject).__name__} cannot have runs") from None
        return self.filter(**{field: subject})

    def for_subject_id(self, subject_id) -> "GraphRunQuerySet":
        """For a subject that may not be a row yet, or that the caller only has the id of."""
        return self.filter(lesson_id=subject_id)

    def owned_by(self, user) -> "GraphRunQuerySet":
        """The runs of this learner's own lessons. The API always starts from here, as it does for lessons."""
        return self.filter(lesson__owner=user)

    def with_subject(self, *, owner: bool = False) -> "GraphRunQuerySet":
        """Fetch each run's subject in the same query (and its owner, for a list that names the learner)."""
        return self.select_related("lesson__owner" if owner else "lesson")


class GraphRun(models.Model):
    """One Celery execution segment of a graph: start, each resume, a retry, a repair… Drives progress streaming."""

    class Graph(models.TextChoices):
        FLOW = "flow", "Lesson flow"
        STUDY_MATERIAL = "study_material", "Extra study sheet"
        RUNTIME_REPAIR = "runtime_repair", "Runtime repair"
        GRADE_TEST = "grade_test", "Test grading"
        QUESTION_BANK = "question_bank", "New test questions"

    class Trigger(models.TextChoices):
        START = "start", "Start"
        RESUME_DIAGNOSTIC = "resume_diagnostic", "Diagnostic answered"
        RESUME_PREREQUISITE = "resume_prerequisite", "Prerequisites answered"
        RESUME_CHOICE = "resume_choice", "Sheet chosen"
        RETRY = "retry", "Retry"
        REPAIR = "repair", "Runtime repair"
        GRADE = "grade", "Test submitted"
        EXTRA_MATERIAL = "extra_material", "Extra sheet"
        RETAKE = "retake", "Test retake"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        PAUSED = "paused", "Paused (waiting for the learner)"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    TERMINAL = {Status.PAUSED, Status.SUCCEEDED, Status.FAILED, Status.CANCELLED}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # SSE channel run:{id}:events
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="runs")
    graph = models.CharField(max_length=20, choices=Graph.choices, default=Graph.FLOW)
    trigger = models.CharField(max_length=30, choices=Trigger.choices)
    payload = models.JSONField(default=dict, blank=True)  # e.g. the resume value or the requested sheet kind
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    node_status = models.JSONField(default=dict, blank=True)  # {node: pending|running|done|retrying|degraded|failed}
    # {node: {started_at, finished_at, retries}}, kept next to node_status (lessons/runner.py): the console's timeline.
    node_timings = models.JSONField(default=dict, blank=True)
    celery_task_id = models.CharField(max_length=80, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    objects = GraphRunQuerySet.as_manager()

    #: the kinds of subject a run can belong to → the column that holds it (a quick quiz joins in phase 9.6)
    SUBJECT_FIELDS = {Lesson: "lesson"}

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_graph_display()} · {self.get_trigger_display()} · {self.status}"

    @property
    def subject(self) -> RunSubject:
        """What the run belongs to. Read this, not `lesson`, outside the code that creates runs."""
        return self.lesson

    @property
    def subject_id(self):
        """Its id, without fetching it."""
        return self.lesson_id

    def fresh_subject(self) -> RunSubject:
        """The subject as the database has it now, because the graph moves its stage in another process."""
        subject = self.subject
        return type(subject).objects.get(pk=subject.pk)

    @property
    def is_active(self) -> bool:
        return self.status in (self.Status.QUEUED, self.Status.RUNNING)


def _default_media_sources():
    return ["wikimedia", "openverse"]


def _default_licenses():
    return ["cc0", "pdm", "cc-by", "cc-by-sa"]


class FlowSettings(models.Model):
    """Singleton edited in the admin. Snapshotted onto each lesson when it starts."""

    diagnostic_questions_per_band = models.PositiveSmallIntegerField(
        default=2, validators=[MinValueValidator(1), MaxValueValidator(4)], help_text="5 bands, so 2 → 10 questions."
    )
    prerequisite_question_count = models.PositiveSmallIntegerField(
        default=5, validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    prereq_trigger_max_correct = models.PositiveSmallIntegerField(
        default=2, help_text="At or below this many diagnostic answers correct, the prerequisite quiz is shown."
    )
    mastery_requires_all_correct = models.BooleanField(
        default=True, help_text="Off: mastery also when only one non-hard answer is wrong."
    )
    final_test_min = models.PositiveSmallIntegerField(default=10)
    final_test_max = models.PositiveSmallIntegerField(default=15)
    max_interactives_per_page = models.PositiveSmallIntegerField(default=3)
    band_fail_below = models.PositiveSmallIntegerField(
        default=30, validators=[MaxValueValidator(100)], help_text="Percent under which an attempt is a Fail."
    )
    band_excellent_above = models.PositiveSmallIntegerField(
        default=90, validators=[MaxValueValidator(100)], help_text="Percent over which an attempt is Excellent."
    )
    question_batch_size = models.PositiveSmallIntegerField(
        default=5,
        validators=[MinValueValidator(5), MaxValueValidator(10)],
        help_text="Questions written per model call (5 to 10).",
    )
    batch_max_long = models.PositiveSmallIntegerField(
        default=1, validators=[MaxValueValidator(10)], help_text="Long answers per batch, unless only long are asked."
    )
    batch_max_short = models.PositiveSmallIntegerField(
        default=2, validators=[MaxValueValidator(10)], help_text="Short answers per batch, unless only short are asked."
    )
    retakes_per_day = models.PositiveSmallIntegerField(
        default=3, validators=[MinValueValidator(1), MaxValueValidator(50)], help_text="Per lesson, in 24 hours."
    )
    alignment_min_score = models.PositiveSmallIntegerField(
        default=3, validators=[MinValueValidator(1), MaxValueValidator(5)], help_text="Out of 5, for every score."
    )
    alignment_max_rounds = models.PositiveSmallIntegerField(default=2)
    render_check_max_rounds = models.PositiveSmallIntegerField(default=2)
    max_auto_runtime_repairs = models.PositiveSmallIntegerField(default=2)
    media_sources = models.JSONField(
        default=_default_media_sources, help_text='Any of "wikimedia", "openverse", "giphy".'
    )
    allowed_media_licenses = models.JSONField(default=_default_licenses)

    class Meta:
        verbose_name = verbose_name_plural = "flow settings"

    def __str__(self):
        return "Flow settings"

    def save(self, *args, **kwargs):
        self.pk = 1  # singleton
        super().save(*args, **kwargs)

    def clean(self):
        """Checked by the admin and by the console, which both build a model form. The test's size is fixed in code
        now, so `final_test_min` and `final_test_max` are no longer asked about."""
        errors = {}
        if self.band_fail_below is not None and self.band_excellent_above is not None:
            if self.band_fail_below >= self.band_excellent_above:
                errors["band_fail_below"] = "The Fail line must be below the Excellent line."
        if self.question_batch_size is not None and not 5 <= self.question_batch_size <= 10:
            errors["question_batch_size"] = "A batch is 5 to 10 questions."
        if errors:
            raise ValidationError(errors)

    @classmethod
    def load(cls) -> "FlowSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def snapshot(self) -> dict:
        return {field.name: getattr(self, field.name) for field in self._meta.concrete_fields if field.name != "id"}
