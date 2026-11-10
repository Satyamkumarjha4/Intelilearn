from django.core.exceptions import ValidationError
from django.db import models


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
