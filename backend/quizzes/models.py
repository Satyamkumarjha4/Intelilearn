"""A quick quiz is a set of questions on a topic, or on lessons the learner has made, taken as often as they like.

It is its own aggregate, not a lesson: it has no pages, no plan and no test. It satisfies the run port (`RunSubject`),
so the runner, Stop and the console treat it like a lesson. Every row hangs off `QuickQuiz.owner`; the API always
filters by the requesting user. The LangGraph thread for a quiz's first run uses `QuickQuiz.id` as its thread id.
"""

import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from lessons.gradable import GradableAttempt
from lessons.models import Lesson

from .stages import IllegalTransition, QuizStage, QuizStageTransitions


class QuickQuizQuerySet(models.QuerySet):
    def owned_by(self, user) -> "QuickQuizQuerySet":
        return self.filter(owner=user)


class QuickQuiz(models.Model):
    class SourceType(models.TextChoices):
        TOPIC = "topic", "A topic"
        LESSONS = "lessons", "Lessons"

    #: fixed once the quiz exists: attempts are compared by them, and a change is a new quiz
    IMMUTABLE = ("config", "config_hash", "source_type", "topic", "owner_id")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="quick_quizzes")
    source_type = models.CharField(max_length=10, choices=SourceType.choices)
    topic = models.CharField(max_length=200)  # the topic, or for lessons a title made from their topics
    config = models.JSONField()  # QuizConfig (graph/quiz_config.py): the count, the kinds and the level mode
    config_hash = models.CharField(max_length=64, db_index=True)  # the same settings give the same hash
    stage = models.CharField(max_length=30, choices=QuizStage.choices, default=QuizStage.PREPARING)
    assessment = models.JSONField(null=True, blank=True)  # the LearnerAssessment once the level is known
    calibration = models.JSONField(null=True, blank=True)  # the pool and the walk so far: server-side only
    config_snapshot = models.JSONField(default=dict, blank=True)  # the model registry used by this quiz
    settings_snapshot = models.JSONField(default=dict, blank=True)  # FlowSettings used by this quiz
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = QuickQuizQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["owner", "-created_at"], name="quickquiz_owner_created_idx")]
        verbose_name_plural = "quick quizzes"

    def __str__(self):
        return f"{self.topic} ({self.get_stage_display()})"

    def save(self, *args, **kwargs):
        if not self._state.adding and (changed := self._changed_settings()):
            raise ValueError(f"A quiz's settings cannot change after it is made ({', '.join(changed)}).")
        super().save(*args, **kwargs)

    @property
    def level(self) -> str:
        """The level the quiz is written at, once it is known."""
        return (self.assessment or {}).get("level", "")

    def _changed_settings(self) -> list[str]:
        stored = QuickQuiz.objects.filter(pk=self.pk).values(*self.IMMUTABLE).first()
        return [name for name, value in (stored or {}).items() if getattr(self, name) != value]

    def advance_to(self, stage: QuizStage, **fields) -> None:
        """Move to `stage` (and set `fields`) if that is a legal move from the *stored* stage.

        Judged against the database, not this instance, because graph nodes and API calls run in different processes.
        Clears any earlier error."""
        current = QuickQuiz.objects.values_list("stage", flat=True).get(pk=self.pk)
        if not QuizStageTransitions().allowed(current, stage):
            raise IllegalTransition(f"A quiz cannot go from {current} to {stage}.")
        self.record(stage=stage, error="", **fields)

    def fail(self, error: str) -> None:
        """Mark the quiz failed with a readable reason. A quiz that is already ready stays usable: what failed was a
        retake, and the retake's own attempt is removed."""
        current = QuickQuiz.objects.values_list("stage", flat=True).get(pk=self.pk)
        if QuizStageTransitions().allowed(current, QuizStage.FAILED):
            self.record(stage=QuizStage.FAILED, error=error)

    def record(self, **fields) -> None:
        """Write only these fields (never the whole row, so a concurrent update elsewhere is not overwritten)."""
        if refused := [name for name in fields if name in self.IMMUTABLE]:
            raise ValueError(f"A quiz's settings cannot change after it is made ({', '.join(refused)}).")
        QuickQuiz.objects.filter(pk=self.pk).update(updated_at=timezone.now(), **fields)
        for name, value in fields.items():
            setattr(self, name, value)


class QuickQuizSource(models.Model):
    """One lesson a quiz is made from: the level its questions are written at and how many of them there are. The
    lesson may be deleted later; the row stays, with the lesson's title, so the quiz keeps its shares."""

    quiz = models.ForeignKey(QuickQuiz, on_delete=models.CASCADE, related_name="sources")
    lesson = models.ForeignKey(Lesson, null=True, blank=True, on_delete=models.SET_NULL, related_name="quiz_sources")
    #: the lesson's id when the quiz was made, kept when the lesson goes: the questions name their lesson by it
    lesson_ref = models.UUIDField()
    title = models.CharField(max_length=200)  # the lesson's title when the quiz was made
    level = models.CharField(max_length=20)  # the level this lesson's questions are written at
    share = models.PositiveSmallIntegerField()  # how many of the quiz's questions are about this lesson

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["quiz", "lesson"], name="unique_lesson_per_quiz")]

    def __str__(self):
        return f"{self.title} ({self.share})"


class QuickQuizAttempt(GradableAttempt):
    """One attempt at a quick quiz (`GradableAttempt`). A retake is a new attempt with new questions."""

    quiz = models.ForeignKey(QuickQuiz, on_delete=models.CASCADE, related_name="attempts")

    class Meta(GradableAttempt.Meta):
        constraints = [
            models.UniqueConstraint(fields=["quiz", "attempt_no"], name="unique_attempt_no_per_quiz"),
            models.UniqueConstraint(
                fields=["quiz"],
                condition=models.Q(status__in=["generating", "in_progress"]),
                name="one_open_attempt_per_quiz",
            ),
        ]

    def __str__(self):
        return f"Attempt {self.attempt_no} of {self.quiz.topic} ({self.get_status_display()})"
