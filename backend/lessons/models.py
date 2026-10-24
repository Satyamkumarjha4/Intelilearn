"""A lesson is one learner's request to learn one topic: diagnostic quiz → lesson or study sheet.

Every lesson-scoped row hangs off `Lesson.owner`; the API always filters by the requesting user.
The LangGraph thread for a lesson uses `Lesson.id` as its thread_id (checkpoints live in Postgres).
"""

import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .stages import IllegalTransition, MaterialKind, Route, Stage, StageTransitions  # noqa: F401  (re-exported)


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

    # Stage A
    assessment = models.JSONField(null=True, blank=True)  # LearnerAssessment
    prerequisites_to_cover = models.JSONField(default=list, blank=True)
    # Stage B
    title = models.CharField(max_length=200, blank=True)
    level = models.CharField(max_length=20, blank=True)
    plan = models.JSONField(null=True, blank=True)  # LessonPlan
    pages = models.JSONField(null=True, blank=True)  # {introduction, core, advanced} → PageContent
    final_test = models.JSONField(null=True, blank=True)  # FinalTest, answers included: never sent as-is
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

    def __str__(self):
        return f"{self.topic} ({self.get_stage_display()})"

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


class TestSubmission(models.Model):
    """One go at the lesson's final test. Several are allowed, so the learner can retake it.

    `result` is the `ScoreCard` (graph/grading.py): at first only what could be marked at once, complete when the
    `grade_test` graph has graded the open-ended answers.
    """

    __test__ = False  # not a pytest test class, whatever its name looks like

    class Status(models.TextChoices):
        GRADING = "grading", "Grading"
        GRADED = "graded", "Graded"
        FAILED = "failed", "Grading failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name="submissions")
    answers = models.JSONField(default=dict)  # {question_id: answer}
    result = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.GRADING)
    error = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    graded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"Test of {self.lesson.topic} ({self.get_status_display()})"


class GraphRun(models.Model):
    """One Celery execution segment of a graph: start, each resume, a retry, a repair… Drives progress streaming."""

    class Graph(models.TextChoices):
        FLOW = "flow", "Lesson flow"
        STUDY_MATERIAL = "study_material", "Extra study sheet"
        RUNTIME_REPAIR = "runtime_repair", "Runtime repair"
        GRADE_TEST = "grade_test", "Test grading"

    class Trigger(models.TextChoices):
        START = "start", "Start"
        RESUME_DIAGNOSTIC = "resume_diagnostic", "Diagnostic answered"
        RESUME_PREREQUISITE = "resume_prerequisite", "Prerequisites answered"
        RESUME_CHOICE = "resume_choice", "Sheet chosen"
        RETRY = "retry", "Retry"
        REPAIR = "repair", "Runtime repair"
        GRADE = "grade", "Test submitted"
        EXTRA_MATERIAL = "extra_material", "Extra sheet"

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
    celery_task_id = models.CharField(max_length=80, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_graph_display()} · {self.get_trigger_display()} · {self.status}"

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

    @classmethod
    def load(cls) -> "FlowSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def snapshot(self) -> dict:
        return {field.name: getattr(self, field.name) for field in self._meta.concrete_fields if field.name != "id"}
