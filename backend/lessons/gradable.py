"""What a lesson's test attempt and a quick quiz's attempt have in common (plan §7.4): the questions served, the
learner's
answers, how it was marked, and the one way out of "in progress".

Both models are abstract children of this base, so the score card, the trend and the grading graph treat them alike. The
base owns the fields and `seal()`; each model adds its owner (a lesson or a quiz), its numbering constraints, and
anything that is only its own (a lesson attempt's follow-up offer).
"""

import uuid

from django.db import models
from django.utils import timezone

from .errors import AttemptSealed


class GradableAttempt(models.Model):
    """One attempt at a set of questions. Numbered from 1 per owner, and at most one is open at a time (the owner's
    model adds the constraints, because the column they apply to is the owner's).

    `questions` is the snapshot of what was served, answer keys included, which is what makes an attempt immutable and
    gradable whatever happens to the record later. Once the attempt leaves `in_progress` its `answers` and `questions`
    never change: `seal()` is the only way out. `result` is the `ScoreCard` (graph/grading.py): complete at once for an
    objective attempt, and when the grading graph has marked the open-ended answers for any other.
    """

    class Status(models.TextChoices):
        GENERATING = "generating", "Preparing questions"
        IN_PROGRESS = "in_progress", "In progress"
        GRADING = "grading", "Grading"  # an attempt with open-ended questions, until a model has marked them
        GRADED = "graded", "Graded"
        FAILED = "failed", "Grading failed"

    OPEN = (Status.GENERATING, Status.IN_PROGRESS)
    SEALED = (Status.GRADING, Status.GRADED, Status.FAILED)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    attempt_no = models.PositiveSmallIntegerField(default=1)  # per owner, from 1
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
    all_blank = models.BooleanField(default=False, help_text="Every answer was blank. Stored, scores 0, no offer.")

    class Meta:
        abstract = True
        ordering = ["-attempt_no"]

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN

    def seal(self, *, answers: dict, status: str, result: dict, band: str, all_blank: bool, now, **also) -> None:
        """Close an attempt that is in progress: its answers are final, and so is what they scored (or, for an attempt
        with open-ended answers, the part of it that could be marked at once). The only way out of `in_progress`; the
        conditional update makes a second call, or a call on a closed attempt, do nothing. `also` is anything else the
        owner's model keeps with a sealed attempt (a lesson attempt's follow-up offer)."""
        graded = status == self.Status.GRADED
        score = result["score"]
        sealed = (
            type(self)
            ._default_manager.filter(pk=self.pk, status=self.Status.IN_PROGRESS)
            .update(
                answers=answers,
                status=status,
                result=result,
                awarded=score["awarded"] if graded else None,
                available=score["available"] if graded else None,
                band=band,
                all_blank=all_blank,
                submitted_at=now,
                graded_at=now if graded else None,
                duration_s=max(0, int((now - self.started_at).total_seconds())),
                **also,
            )
        )
        if not sealed:
            raise AttemptSealed()
        self.refresh_from_db()
