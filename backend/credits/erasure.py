"""Erasing an account (credits plan P5, phase 10.3).

A person can ask us to delete their account. The user cannot simply be deleted: the credit ledger is append-only and
the user
is a protected key of it. So the account is **anonymised in place**: the email and name are scrubbed, the profile
emptied, the
password made unusable, the account made inactive and marked deleted, and everything the learner made is erased
(lessons,
quizzes, their checkpoints and model calls, their streak). What remains is an anonymous record of money, and it adds up:
open reserves are released first, then the credits left are written off in one `forfeit` row. No ledger row is ever
edited.

It is safe to repeat: an erased account is reported as such and nothing more happens, and an attempt that stopped
half way is
finished by the next (the anonymising comes last).
"""

import logging
from dataclasses import dataclass

from django.contrib.admin.models import LogEntry
from django.contrib.auth.hashers import make_password
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken

from accounts.models import OutboundMail, Profile, User
from console.audit import AuditTrail
from console.models import AuditEntry
from lessons.models import Lesson
from lessons.services import LessonService
from quizzes.models import QuickQuiz
from quizzes.services import QuickQuizService

from .errors import HoldNotHeld
from .ledger import Ledger
from .models import CreditHold, StreakDay, StreakState, Wallet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ErasureReport:
    user_id: object
    already_erased: bool = False
    dry_run: bool = False
    lessons: int = 0
    quizzes: int = 0
    released_holds: int = 0
    forfeited: int = 0  # credits written off (in a dry run, what would be)
    tokens: int = 0  # refresh tokens deleted
    sessions: int = 0  # admin sessions deleted
    admin_log: int = 0  # Django admin log rows about the account deleted
    audit_scrubbed: int = 0  # change-log entries about the learner that lost their free text
    mail: int = 0  # rows of the mail log sent to the account's address, deleted


class UserDataMap:
    """Every table that points at a user, and what erasing the account does to it. It is documentation that a test
    holds to account: a relation to `User` that is not listed here, or a row here that no longer exists, fails
    `test_account_erasure_traces`, so a new table cannot be added without deciding what becomes of a person's rows.

    The user row itself is never deleted: the credit ledger and the payment records are append-only (or protected), and
    the law asks for them, so the row is **anonymised in place** and what stays is an anonymous record of money."""

    ERASED, SCRUBBED, KEPT, CLEARED = "erased", "scrubbed", "kept without identity", "links cleared"
    FATES = (ERASED, SCRUBBED, KEPT, CLEARED)

    #: "app.Model.field" → (fate, why). The field is the one that points at the user.
    TABLES: dict[str, tuple[str, str]] = {
        "lessons.Lesson.owner": (ERASED, "deleted through LessonService, with everything that hangs on a lesson"),
        "quizzes.QuickQuiz.owner": (ERASED, "deleted through QuickQuizService, with its attempts and checkpoints"),
        "accounts.Profile.user": (SCRUBBED, "the row stays (the app expects one) with every answer emptied"),
        "accounts.User_groups.user": (CLEARED, "the account's groups are removed"),
        "accounts.User_user_permissions.user": (CLEARED, "the account's permissions are removed"),
        "token_blacklist.OutstandingToken.user": (ERASED, "every refresh token is deleted, with its blacklist row"),
        "credits.StreakDay.user": (ERASED, "the days studied are deleted"),
        "credits.StreakState.user": (ERASED, "the cached streak is deleted"),
        "credits.Wallet.user": (KEPT, "append-only ledger, protected key; credits left are forfeited"),
        "credits.CreditBucket.user": (KEPT, "part of the ledger: emptied by the forfeit row, never edited"),
        "credits.CreditHold.user": (KEPT, "part of the ledger: open reserves are released first"),
        "credits.CreditTransaction.user": (KEPT, "the append-only ledger; carries no email or name"),
        "credits.PlanPurchase.user": (KEPT, "a record of what was bought; accounts and tax rules ask for it"),
        "credits.PlanPeriod.user": (KEPT, "a record of what a plan gave, period by period"),
        "payments.PaymentOrder.user": (KEPT, "a record of money taken, with its refunds; the provider keeps the rest"),
        "admin.LogEntry.user": (KEPT, "rows where this account was the actor stay (staff accountability)"),
        "console.AuditEntry.actor": (KEPT, "the change log is not edited; a learner makes no changes"),
    }  # fmt: skip

    #: Places that hold a person's data without a relation to the user row.
    OUTSIDE: dict[str, tuple[str, str]] = {
        "sessions.Session": (ERASED, "admin sessions whose `_auth_user_id` is the account are deleted"),
        "admin.LogEntry (about the account)": (ERASED, "rows about the account and wallet quote the name and email"),
        "console.AuditEntry (about the learner)": (SCRUBBED, "free-text reasons are removed; actions and amounts stay"),
        "accounts.OutboundMail (sent to the address)": (
            ERASED,
            "the mail log rows sent to the account's address are deleted",
        ),
        "llm_registry.ModelCall": (ERASED, "deleted by lesson and quiz id with the lesson or quiz"),
        "LangGraph checkpoint tables": (ERASED, "the flow and quiz threads are deleted with the lesson or quiz"),
        "Redis caches": (ERASED, "idempotency answers and suggestion caches expire on their own within hours"),
    }  # fmt: skip


class AccountTraces:
    """The places a person leaves a trace without having made a lesson: the refresh tokens that keep a sign-in alive,
    the sessions of the Django admin, the admin's own log of what was done to the account (it quotes the name and the
    email), and the free-text reasons staff typed in the change log when they moved the learner's credits."""

    #: keys of a change-log entry's before/after that can hold what a person wrote or is called
    FREE_TEXT = ("reason", "email", "name")

    def __init__(self, user: User):
        self.user = user

    def tokens(self):
        return OutstandingToken.objects.filter(user=self.user)

    def session_keys(self) -> list[str]:
        """The live sessions of this account. Sessions hold no relation to the user, so each is read."""
        wanted = str(self.user.pk)
        live = Session.objects.filter(expire_date__gt=timezone.now())
        return [s.session_key for s in live.iterator() if s.get_decoded().get("_auth_user_id") == wanted]

    def admin_log(self):
        """Rows the admin wrote about this account or its wallet. Rows where the account was the actor are kept."""
        kinds = ContentType.objects.get_for_models(User, Wallet).values()
        return LogEntry.objects.filter(content_type__in=list(kinds), object_id=str(self.user.pk))

    def audit(self):
        """Change-log entries about the learner (a credits change, the exempt switch)."""
        return AuditEntry.objects.filter(target_id=str(self.user.pk))

    def mail(self):
        """The mail log rows sent to the account's address: they have no relation to the user, only the address."""
        return OutboundMail.objects.filter(to_email__iexact=self.user.email)

    def counts(self) -> dict[str, int]:
        return {
            "tokens": self.tokens().count(),
            "sessions": len(self.session_keys()),
            "admin_log": self.admin_log().count(),
            "audit_scrubbed": self.audit().count(),
            "mail": self.mail().count(),
        }

    def forget(self) -> dict[str, int]:
        """Delete the tokens, sessions and admin log rows, and take the free text out of the change log."""
        found = self.counts()
        self.tokens().delete()  # the blacklist rows hang on the tokens and go with them
        Session.objects.filter(session_key__in=self.session_keys()).delete()
        self.admin_log().delete()
        self.mail().delete()
        for entry in self.audit():
            AuditEntry.objects.filter(pk=entry.pk).update(
                before=self._cleaned(entry.before), after=self._cleaned(entry.after)
            )
        return found

    @classmethod
    def _cleaned(cls, value):
        if isinstance(value, dict):
            return {key: cls._cleaned(item) for key, item in value.items() if key not in cls.FREE_TEXT}
        if isinstance(value, list):
            return [cls._cleaned(item) for item in value]
        return value


class AccountErasure:
    REASON = "Account erased"

    def __init__(
        self,
        ledger: Ledger | None = None,
        lessons: LessonService | None = None,
        quizzes: QuickQuizService | None = None,
        trail: AuditTrail | None = None,
    ):
        self.ledger = ledger or Ledger()
        self.lessons = lessons or LessonService()
        self.quizzes = quizzes or QuickQuizService()
        self.trail = (
            trail  # when given, one `learner.erase` entry is written in the same transaction as the anonymising
        )

    def erase(self, user, dry_run: bool = False) -> ErasureReport:
        user = User.objects.get(pk=user.pk)
        if user.deleted_at is not None:
            return ErasureReport(user.pk, already_erased=True, dry_run=dry_run)
        lessons = list(Lesson.objects.filter(owner=user))
        quizzes = list(QuickQuiz.objects.filter(owner=user))
        held = list(CreditHold.objects.filter(user=user, status=CreditHold.Status.HELD))
        if dry_run:
            would_forfeit = self.ledger.balance(user) + sum(hold.amount for hold in held)
            return ErasureReport(user.pk, dry_run=True, lessons=len(lessons), quizzes=len(quizzes),
                                 released_holds=len(held), forfeited=would_forfeit,
                                 **AccountTraces(user).counts())  # fmt: skip
        released = self._release(held)
        for lesson in lessons:
            self.lessons.delete(lesson)
        for quiz in quizzes:
            self.quizzes.delete(quiz)
        facts = {"lessons": len(lessons), "quizzes": len(quizzes), "released_holds": released}
        forfeited, traces = self._close(user, facts)
        logger.info("Erased account %s", user.pk)
        return ErasureReport(user.pk, lessons=len(lessons), quizzes=len(quizzes), released_holds=released,
                             forfeited=forfeited, **traces)  # fmt: skip

    def _release(self, holds: list[CreditHold]) -> int:
        released = 0
        for hold in holds:
            try:
                self.ledger.release(hold.pk)
                released += 1
            except HoldNotHeld:
                pass  # settled meanwhile
        return released

    def _close(self, user: User, facts: dict[str, int]) -> tuple[int, dict[str, int]]:
        """Write off what is left, remove the traces and anonymise, together. Returns the credits forfeited and the
        counts of what was removed."""
        with transaction.atomic():
            forfeited = 0
            if Wallet.objects.filter(pk=user.pk).exists():
                done = self.ledger.forfeit(user, f"forfeit:{user.pk}", reason=self.REASON)
                forfeited = -done.transaction.amount
            StreakDay.objects.filter(user=user).delete()
            StreakState.objects.filter(user=user).delete()
            traces = AccountTraces(user).forget()
            Profile.objects.filter(user=user).update(
                education_level="", grade_or_year="", field_of_study="", preferred_language="en",
                learning_preference="", goal="", notes="", timezone="", timezone_changed_at=None,
            )  # fmt: skip
            anonymous = f"deleted-{user.pk}@erased.invalid"
            User.objects.filter(pk=user.pk).update(
                email=anonymous, email_canonical=anonymous, email_verified_at=None, email_verification_source="",
                name="", password=make_password(None), is_active=False,
                is_staff=False, is_superuser=False, last_login=None, deleted_at=self.ledger.clock.now(),
            )  # fmt: skip
            user.groups.clear()
            user.user_permissions.clear()
            if self.trail is not None:  # counts and nothing that names the person
                self.trail.record(
                    "learner.erase", "learner", user.pk,
                    before={**facts, "credits_forfeited": forfeited, "refresh_tokens": traces["tokens"],
                            "sessions": traces["sessions"]},
                    after={"erased": True},
                )  # fmt: skip
        return forfeited, traces
