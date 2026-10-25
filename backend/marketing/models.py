from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from pydantic import ValidationError as PydanticValidationError

from .schemas import Outcome


class DemoQuestion(models.Model):
    """One question of the landing page's try-it card. The page shows a random active one on every load, with the
    outcome that follows from the visitor's answer. Curated in the Django admin."""

    OPTION_COUNT = 3

    subject = models.CharField(max_length=60)
    level_label = models.CharField(max_length=40, help_text='Who it is pitched at, for example "Class 8" or "College".')
    band = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Difficulty: 1 Basics, 2 Easy, 3 Medium, 4 Hard, 5 Expert.",
    )
    question = models.CharField(max_length=200, help_text="Short: it should fit on two lines of the card.")
    options = models.JSONField(default=list, help_text="Exactly three texts, as a JSON list.")
    correct_index = models.PositiveSmallIntegerField(help_text="Which option is right: 0, 1 or 2.")
    outcome_right = models.JSONField(help_text='{"level": 1-5, "level_label": "...", "lesson_start": "..."}')
    outcome_wrong = models.JSONField(help_text='The same, for a wrong answer or "I don\'t know".')
    is_active = models.BooleanField(default=True, help_text="Only active questions are shown.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.question

    def clean(self):
        errors = {}
        self._check_text(errors)
        self._check_options(errors)
        right, wrong = self._outcome("outcome_right", errors), self._outcome("outcome_wrong", errors)
        if right and wrong and right.level < wrong.level:
            errors["outcome_right"] = "A right answer cannot leave the learner at a lower level than a wrong one."
        if errors:
            raise ValidationError(errors)

    def _check_text(self, errors: dict) -> None:
        for field in ("subject", "level_label", "question"):
            if not (getattr(self, field) or "").strip():
                errors[field] = "This must not be blank."

    def _check_options(self, errors: dict) -> None:
        options = self.options
        if not (isinstance(options, list) and len(options) == self.OPTION_COUNT):
            errors["options"] = "Give exactly three options, as a JSON list of three texts."
        elif not all(isinstance(option, str) and option.strip() for option in options):
            errors["options"] = "Every option must be a text that is not blank."
        elif len({option.strip().casefold() for option in options}) != len(options):
            errors["options"] = "The options must all be different."
        index = self.correct_index
        if not (isinstance(index, int) and 0 <= index < self.OPTION_COUNT):
            errors["correct_index"] = "The correct answer is the number of an option: 0, 1 or 2."

    def _outcome(self, field: str, errors: dict) -> Outcome | None:
        try:
            return Outcome.model_validate(getattr(self, field))
        except PydanticValidationError as exc:
            problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'outcome'}: {e['msg']}" for e in exc.errors())
            errors[field] = f"Needs a level (1 to 5), a level label and a lesson start. {problems}"
            return None
