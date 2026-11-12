import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone

from .emailrules.canonical import EmailCanonicalizer, MalformedEmail
from .timezones import TimeZoneNames


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, verified=False, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        if (
            verified
        ):  # made by code (a script, a fixture, `createsuperuser`): the operator vouches, nobody proved the inbox
            extra_fields.setdefault("email_verified_at", timezone.now())
            extra_fields.setdefault("email_verification_source", User.VerificationSource.OPERATOR)
        user = self.model(email=self.normalize_email(email).lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, verified=False, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, verified=verified, **extra_fields)

    def create_superuser(self, email, password=None, verified=True, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("A superuser must have is_staff=True and is_superuser=True.")
        return self._create_user(email, password, verified=verified, **extra_fields)

    def get_by_natural_key(self, username):
        return self.get(email__iexact=username)  # the alias-aware lookup arrives with sign-up in phase 11.1


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
    # Set when the account was erased (`credits.erasure.AccountErasure`): the row stays, anonymised, because the
    # credit ledger
    # is append-only and refers to it; everything personal is gone.
    deleted_at = models.DateTimeField(null=True, blank=True)

    # Whether and how the email was proved (phase 11): the signup credits are given only for a verified address. The
    # address stays as typed in `email`; `email_canonical` is only for "have we seen this person" (one account per
    # inbox).
    email_verified_at = models.DateTimeField(null=True, blank=True)
    email_verification_source = models.CharField(max_length=12, blank=True, default="")
    email_canonical = models.CharField(max_length=320, unique=True, editable=False)

    class VerificationSource(models.TextChoices):
        CODE = "code", "A code sent to the address"
        GOOGLE = "google", "Google said it is verified"
        MICROSOFT = "microsoft", "Microsoft said it is verified"
        STAFF = "staff", "Marked verified in the console"
        OPERATOR = "operator", "Made by code (createsuperuser, a script)"
        LEGACY = "legacy", "Existed before verification; never proved"

    #: The sources where the **owner of the inbox** proved it. Only these let a later sign-in link to the account.
    PROVED_BY_OWNER = frozenset({"code", "google", "microsoft"})

    #: The version of the Terms of Use and Privacy Policy a new account agrees to (the date they were last updated).
    TERMS_VERSION = "2026-11-07"

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

    @classmethod
    def from_db(cls, db, field_names, values):
        user = super().from_db(db, field_names, values)
        user._remember_email()
        return user

    def refresh_from_db(self, using=None, fields=None, **kwargs):
        super().refresh_from_db(using=using, fields=fields, **kwargs)
        if fields is None or "email" in fields:
            self._remember_email()

    def _remember_email(self) -> None:
        """What the address was when it was read, so `save` can tell it was changed (and does not trust the old
        proof)."""
        self._loaded_email = self.__dict__.get("email")

    def save(self, *args, **kwargs):
        """Keeps the canonical email true, and takes the proof away from an address that was changed: whoever
        proved the old
        one did not prove the new one. Nothing lets a learner change their email today (docs, phase 11 plan D17); this
        is for the day some path does."""
        changed = not self._state.adding and self._loaded_email is not None and self.email != self._loaded_email
        touched = ["email_canonical"]
        if changed or not self.email_canonical:
            self.email_canonical = self._canonical()
        if changed:
            self.email_verified_at, self.email_verification_source = None, ""
            touched += ["email_verified_at", "email_verification_source"]
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and changed:
            kwargs["update_fields"] = {*update_fields, *touched}
        super().save(*args, **kwargs)
        self._remember_email()

    _loaded_email = None

    def _canonical(self) -> str:
        try:
            return EmailCanonicalizer.of(self.email)
        except MalformedEmail:
            return (self.email or "").strip().lower()  # forms and serializers judge addresses; a save must not crash

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def email_proved_by_owner(self) -> bool:
        """The owner of the inbox proved it (by a code, or by Google or Microsoft saying so); a flag set by the
        operator,
        a staff member or the migration is not that."""
        return self.is_email_verified and self.email_verification_source in self.PROVED_BY_OWNER


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
    # The learner's day is the day in this zone (an IANA name). Blank until set; the zone in force is then Asia/Kolkata.
    # The first value (from the browser at sign-up) leaves `timezone_changed_at` empty; a later change stamps it and
    # locks the next change for 30 days (`ProfileTimezone`).
    timezone = models.CharField(max_length=TimeZoneNames.MAX_LENGTH, blank=True)
    timezone_changed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile of {self.user}"

    @property
    def effective_timezone(self) -> str:
        return TimeZoneNames.effective(self.timezone)

    @property
    def is_complete(self) -> bool:
        return all(getattr(self, field) for field in self.REQUIRED_FOR_ONBOARDING)


class AuthSettings(models.Model):
    """Singleton: switches of the sign-in rules that staff change in the console (audited), the way `CreditSettings` is.
    Secrets (the Turnstile keys) are never here: they stay in the environment."""

    captcha_enabled = models.BooleanField(
        default=False, help_text="Ask a visitor to pass a challenge when signing up and asking for a code (phase 11.4)."
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "auth settings"

    def __str__(self):
        return "Sign-in settings"

    @classmethod
    def load(cls) -> "AuthSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class OutboundMail(models.Model):
    """One email the app asked a mailer to send: what kind, to whom, and whether it went. It is how the console
    answers "did
    the email go out?". It holds no code and no body, except on the throwaway test stack, whose `outbox` backend
    keeps the
    text so a browser test can read the code. Rows are purged after 30 days; they carry no relation to a user, so
    erasing
    an account deletes the rows sent to its address (`UserDataMap.OUTSIDE`)."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"

    kind = models.CharField(max_length=30)
    to_email = models.EmailField()
    subject = models.CharField(max_length=200, blank=True)
    backend = models.CharField(max_length=20)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    attempts = models.PositiveSmallIntegerField(default=0)
    provider_message_id = models.CharField(max_length=200, blank=True)
    error = models.CharField(max_length=255, blank=True, help_text="A short reason, never a code or a body.")
    body_text = models.TextField(blank=True, help_text="Kept by the throwaway-stack outbox backend only.")
    created_at = models.DateTimeField(default=timezone.now)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["to_email", "-created_at"]), models.Index(fields=["created_at"])]

    def __str__(self):
        return f"{self.kind} to {self.to_email} ({self.status})"
