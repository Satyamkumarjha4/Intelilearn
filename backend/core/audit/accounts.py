"""How a persona's account comes to exist (Strategy, one class per way of signing in).

Each way makes the account through the same class the real sign-up uses (`AccountActivation`), so a persona has what
a real learner has: a verified address, the signup record, a profile and, once announced, the signup credits. Making
the account twice finds the first one: the password is set again (so it always matches the file the audit keeps) and
nothing else changes.
"""

from abc import ABC, abstractmethod

from django.utils import timezone

from accounts.abuse.records import SignupRecords
from accounts.identity.provider import VerifiedIdentity
from accounts.models import Profile, SignupRecord, User
from accounts.verification.activation import AccountActivation

from .personas import Persona


class AccountKind(ABC):
    sign_in: str

    @abstractmethod
    def create(self, persona: Persona, password: str) -> User:
        """A new account for the persona (the caller has checked there is none)."""

    def ensure(self, persona: Persona, password: str) -> tuple[User, bool]:
        """The persona's account and whether this call made it."""
        existing = User.objects.filter(email__iexact=persona.email).first()
        if existing is not None:
            self.refresh(existing, persona, password)
            return existing, False
        user = self.create(persona, password)
        AccountActivation.announce(user)  # the signup credits, once
        return user, True

    def refresh(self, user: User, persona: Persona, password: str) -> None:
        """What a second run puts right: the staff flag and, where there is one, the password."""
        user.is_staff = persona.staff
        user.save(update_fields=["is_staff"])


class PasswordAccounts(AccountKind):
    sign_in = "password"

    def create(self, persona: Persona, password: str) -> User:
        now = timezone.now()
        user = User(
            email=persona.email,
            name=persona.name,
            terms_accepted_at=now,
            terms_version=User.TERMS_VERSION,
            email_verified_at=now,
            email_verification_source=User.VerificationSource.OPERATOR
            if persona.staff
            else User.VerificationSource.CODE,
            is_staff=persona.staff,
        )
        user.set_password(password)
        user.save()  # the profile is made by the post_save receiver
        SignupRecords().record(user, None, SignupRecord.Method.CODE)
        return user

    def refresh(self, user: User, persona: Persona, password: str) -> None:
        user.set_password(password)
        user.is_staff = persona.staff
        user.save(update_fields=["password", "is_staff"])


class GoogleAccounts(AccountKind):
    """An account made by the stand-in Google provider's identity: linked, verified by it, and no password at all."""

    sign_in = "google"

    def create(self, persona: Persona, password: str) -> User:
        identity = VerifiedIdentity(
            provider="fake",
            subject=f"audit-{persona.slug}",
            email=persona.email,
            email_verified=True,
            name=persona.name,
            verification_source="google",
        )
        return AccountActivation().create_from_identity(identity, persona.name, "Asia/Kolkata", None)


class PersonaAccounts:
    """The kind of account for each persona's `sign_in`."""

    def __init__(self, *kinds: AccountKind):
        self._kinds = {kind.sign_in: kind for kind in (kinds or (PasswordAccounts(), GoogleAccounts()))}

    def ensure(self, persona: Persona, password: str) -> tuple[User, bool]:
        return self._kinds[persona.sign_in].ensure(persona, password)


class PersonaProfiles:
    """A filled-in profile (so onboarding is skipped) in the persona's language, or the blank one a new learner has."""

    FILLED = {
        "education_level": Profile.EducationLevel.SCHOOL,
        "grade_or_year": "9",
        "learning_preference": Profile.LearningPreference.MIXED,
        "goal": Profile.Goal.EXAM_PREP,
    }

    def apply(self, user: User, persona: Persona) -> None:
        profile = user.profile
        profile.preferred_language = persona.language
        fields = ["preferred_language", "updated_at"]
        if persona.onboarded:
            for name, value in self.FILLED.items():
                setattr(profile, name, value)
            fields += list(self.FILLED)
        profile.save(update_fields=fields)
