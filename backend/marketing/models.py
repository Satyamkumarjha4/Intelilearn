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


class Testimonial(models.Model):
    """One quote of the landing page's "What learners say". Curated in the console and shown to every visitor under the
    person's name, so two rules are kept twice, in `clean` (a clear message for the console) and in a database
    constraint (so nothing can get round it): a testimonial is published only when the learner's consent is confirmed,
    and a sample (a placeholder made by `seed_sample_testimonials` for a developer's machine) is never published."""

    __test__ = False  # not a pytest class, whatever its name suggests

    QUOTE_MAX = 300

    name = models.CharField(max_length=80, help_text="As the learner agreed to be shown, for example a first name.")
    context = models.CharField(max_length=80, help_text='Who they are, for example "Class 12 student".')
    quote = models.CharField(max_length=QUOTE_MAX)
    rating = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Stars, 1 to 5. Leave empty for none.")
    position = models.PositiveIntegerField(default=0, help_text="Where it comes in the list: lowest first.")
    is_published = models.BooleanField(default=False, help_text="Shown on the landing page.")
    consent_confirmed = models.BooleanField(
        default=False, help_text="The learner agreed to be quoted here. Needed to publish."
    )
    is_sample = models.BooleanField(default=False, help_text="Made for a developer's machine: never published.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(is_published=False) | (models.Q(consent_confirmed=True) & models.Q(is_sample=False)),
                name="testimonial_published_needs_consent_and_real",
            ),
            models.CheckConstraint(
                condition=models.Q(rating__isnull=True) | models.Q(rating__gte=1, rating__lte=5),
                name="testimonial_rating_one_to_five",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        errors = {}
        for field in ("name", "context", "quote"):
            if not (getattr(self, field) or "").strip():
                errors[field] = "This must not be blank."
        if self.rating is not None and not 1 <= self.rating <= 5:
            errors["rating"] = "The rating is from 1 to 5 stars, or empty."
        if self.is_published and self.is_sample:
            errors["is_published"] = "A sample cannot be published: it is a placeholder for development only."
        elif self.is_published and not self.consent_confirmed:
            errors["is_published"] = (
                "Confirm consent (the learner agreed to be quoted) before publishing, and keep it confirmed."
            )
        if errors:
            raise ValidationError(errors)
