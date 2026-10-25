import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self.normalize_email(email).lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("A superuser must have is_staff=True and is_superuser=True.")
        return self._create_user(email, password, **extra_fields)

    def get_by_natural_key(self, username):
        return self.get(email__iexact=username)


class User(AbstractBaseUser, PermissionsMixin):
    """The only kind of user: a learner who signs in with email and password."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=150)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False, help_text="Can sign in to the Django admin.")
    date_joined = models.DateTimeField(default=timezone.now)
    # What the person agreed to when they created the account (Terms of Use and Privacy Policy, version = their date).
    # Accounts made before the terms existed have neither.
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    terms_version = models.CharField(max_length=20, blank=True)

    #: The version of the Terms of Use and Privacy Policy a new account agrees to (the date they were last updated).
    TERMS_VERSION = "2026-10-25"

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        ordering = ["email"]

    def __str__(self):
        return self.email

    def clean(self):
        super().clean()
        self.email = self.__class__.objects.normalize_email(self.email).lower()


class Profile(models.Model):
    """What the tutor knows about the learner; filled in during onboarding and editable later."""

    class EducationLevel(models.TextChoices):
        SCHOOL = "school", "School"
        UNDERGRADUATE = "undergraduate", "Undergraduate"
        POSTGRADUATE = "postgraduate", "Postgraduate"
        PROFESSIONAL = "professional", "Working professional"
        SELF_LEARNER = "self_learner", "Self-learner"

    # The labels are served by GET /api/profile/options, and the lesson graph writes them into its prompts
    # (graph/profile.py), so changing one changes what the models read.
    class LearningPreference(models.TextChoices):
        VISUAL = "visual", "Visual"
        READING = "reading", "Reading"
        HANDS_ON = "hands_on", "Hands-on"
        MIXED = "mixed", "Mixed"

    class Goal(models.TextChoices):
        EXAM_PREP = "exam_prep", "Exam preparation"
        DEEP_UNDERSTANDING = "deep_understanding", "Deep understanding"
        QUICK_OVERVIEW = "quick_overview", "Quick overview"
        INTERVIEW_PREP = "interview_prep", "Interview preparation"

    class PreferredLanguage(models.TextChoices):
        ENGLISH = "en", "English"
        HINDI = "hi", "Hindi"
        SPANISH = "es", "Spanish"
        FRENCH = "fr", "French"
        GERMAN = "de", "German"

    NOTES_MAX_LENGTH = 2000

    # Fields a profile needs before lessons can be tailored (see `is_complete`).
    REQUIRED_FOR_ONBOARDING = ("education_level", "learning_preference", "goal")

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    education_level = models.CharField(max_length=20, choices=EducationLevel.choices, blank=True)
    grade_or_year = models.CharField(max_length=100, blank=True)
    field_of_study = models.CharField(max_length=150, blank=True)
    preferred_language = models.CharField(
        max_length=10, choices=PreferredLanguage.choices, default=PreferredLanguage.ENGLISH
    )
    learning_preference = models.CharField(max_length=20, choices=LearningPreference.choices, blank=True)
    goal = models.CharField(max_length=20, choices=Goal.choices, blank=True)
    notes = models.TextField(max_length=NOTES_MAX_LENGTH, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile of {self.user}"

    @property
    def is_complete(self) -> bool:
        return all(getattr(self, field) for field in self.REQUIRED_FOR_ONBOARDING)
