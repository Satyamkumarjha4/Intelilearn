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
        user = self.model(email=self.normalize_email(email), **extra_fields)  # as typed: the domain only is lowercased
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
        """Sign-in looks the account up by its canonical email, so an alias of an address finds the same account."""
        try:
            return self.get(email_canonical=EmailCanonicalizer.of(username))
        except MalformedEmail as error:
            raise self.model.DoesNotExist from error


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
        self.email = self.__class__.objects.normalize_email(self.email)

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


class PendingSignup(models.Model):
    """A sign-up waiting for its code. **It is not an account**: there is no `User`, no session and no credits until
    the right code arrives with the matching ticket (`lc_signup`, which holds this row's id). One row per canonical
    email: a second register deletes it and makes a new row with a **new id**, so the first browser's ticket matches
    nothing."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(help_text="As typed: what the code is sent to and the account will show.")
    email_canonical = models.CharField(max_length=320, unique=True)
    name = models.CharField(max_length=150)
    password_hash = models.CharField(max_length=128, help_text="Never shown, and never copied by a staff approval.")
    created_at = models.DateTimeField(default=timezone.now)  # above `timezone`: the field below hides the module
    terms_accepted_at = models.DateTimeField()
    terms_version = models.CharField(max_length=20)
    expires_at = models.DateTimeField()
    timezone = models.CharField(max_length=TimeZoneNames.MAX_LENGTH, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Sign-up of {self.email}"


class VerificationCode(models.Model):
    """One code sent to an email, for one purpose. Only a keyed hash of the code is kept (`CodeHasher`); the code never
    reaches the database, a log or a staff screen. **At most one live code per `(purpose, email)`**: the partial unique
    index below is what holds that when two requests race."""

    class Purpose(models.TextChoices):
        SIGNUP = "signup", "Finish creating an account"
        LOGIN = "login", "Finish signing in (an unverified account)"
        RESET = "reset", "Choose a new password"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purpose = models.CharField(max_length=10, choices=Purpose.choices)
    email_canonical = models.CharField(max_length=320)
    pending = models.ForeignKey(PendingSignup, null=True, blank=True, on_delete=models.CASCADE, related_name="codes")
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="verification_codes")
    code_hash = models.CharField(max_length=64)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    invalidated_at = models.DateTimeField(null=True, blank=True)
    requested_ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["purpose", "email_canonical"],
                condition=models.Q(consumed_at__isnull=True, invalidated_at__isnull=True),
                name="one_live_code_per_purpose_and_email",
            )
        ]
        indexes = [models.Index(fields=["email_canonical", "-created_at"])]

    def __str__(self):
        return f"{self.purpose} code for {self.email_canonical}"


class EmailLock(models.Model):
    """An email whose codes keep dying (three within an hour): it checks no more codes until `locked_until`. A row, not
    a cache entry, so the console can show it and clear it. Keyed on the canonical email whether or not an account has
    it, so a lock cannot be used to find accounts."""

    email_canonical = models.CharField(max_length=320, unique=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    strikes = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Lock on {self.email_canonical}"


class SignupRecord(models.Model):
    """Who created an account, from where and how: the counters of the abuse board (phase 11.4) read it. It holds an
    address, so it is erased with the account and purged after 30 days."""

    class Method(models.TextChoices):
        CODE = "code", "Email with a code"
        GOOGLE = "google", "Google"
        MICROSOFT = "microsoft", "Microsoft"
        STAFF = "staff", "Approved in the console"

    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="signup_records")
    ip = models.GenericIPAddressField(null=True, blank=True)
    email_domain = models.CharField(max_length=255)
    method = models.CharField(max_length=10, choices=Method.choices)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["-created_at"]), models.Index(fields=["ip", "-created_at"])]

    def __str__(self):
        return f"{self.method} sign-up from {self.email_domain}"


class ExternalIdentity(models.Model):
    """A sign-in provider's account linked to one of ours (Google; Microsoft later). The key is `(provider, subject)`,
    the provider's stable id, never the email (which can change and, for some providers, is not always the person's).
    Phase 11.2 reads it (an account that signs in with Google and has no password is not sent a reset code); 11.3 makes
    the rows."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="identities")
    provider = models.CharField(max_length=20)
    subject = models.CharField(max_length=255)
    email_at_link = models.EmailField(blank=True)
    hosted_domain = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_sign_in_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["provider", "subject"], name="one_account_per_identity")]

    def __str__(self):
        return f"{self.provider} identity of {self.user_id}"


class AuthEvent(models.Model):
    """Something the abuse board counts that has no account to hang on: a sign-up refused for a throwaway address, a
    code check that failed, a challenge that was not passed. It holds the visitor's address and the email's **domain**
    (never the address itself) and nothing that names a person, so it has no relation to a user; it is purged after 30
    days."""

    class Kind(models.TextChoices):
        DISPOSABLE_REFUSED = "disposable_refused", "A throwaway email address was refused"
        CHECK_FAILED = "check_failed", "A code was entered wrongly"
        CAPTCHA_FAILED = "captcha_failed", "The sign-up challenge was not passed"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    ip = models.GenericIPAddressField(null=True, blank=True)
    email_domain = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["kind", "-created_at"]), models.Index(fields=["ip", "-created_at"])]

    def __str__(self):
        return f"{self.kind} from {self.ip or 'an unknown address'}"
