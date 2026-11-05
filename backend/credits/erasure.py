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

from django.contrib.auth.hashers import make_password
from django.db import transaction

from accounts.models import Profile, User
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


class AccountErasure:
    REASON = "Account erased"

    def __init__(
        self,
        ledger: Ledger | None = None,
        lessons: LessonService | None = None,
        quizzes: QuickQuizService | None = None,
    ):
        self.ledger = ledger or Ledger()
        self.lessons = lessons or LessonService()
        self.quizzes = quizzes or QuickQuizService()

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
                                 released_holds=len(held), forfeited=would_forfeit)  # fmt: skip
        released = self._release(held)
        for lesson in lessons:
            self.lessons.delete(lesson)
        for quiz in quizzes:
            self.quizzes.delete(quiz)
        forfeited = self._close(user)
        logger.info("Erased account %s", user.pk)
        return ErasureReport(user.pk, lessons=len(lessons), quizzes=len(quizzes), released_holds=released,
                             forfeited=forfeited)  # fmt: skip

    def _release(self, holds: list[CreditHold]) -> int:
        released = 0
        for hold in holds:
            try:
                self.ledger.release(hold.pk)
                released += 1
            except HoldNotHeld:
                pass  # settled meanwhile
        return released

    def _close(self, user: User) -> int:
        """Write off what is left and anonymise, together."""
        with transaction.atomic():
            forfeited = 0
            if Wallet.objects.filter(pk=user.pk).exists():
                done = self.ledger.forfeit(user, f"forfeit:{user.pk}", reason=self.REASON)
                forfeited = -done.transaction.amount
            StreakDay.objects.filter(user=user).delete()
            StreakState.objects.filter(user=user).delete()
            Profile.objects.filter(user=user).update(
                education_level="", grade_or_year="", field_of_study="", preferred_language="en",
                learning_preference="", goal="", notes="", timezone="", timezone_changed_at=None,
            )  # fmt: skip
            User.objects.filter(pk=user.pk).update(
                email=f"deleted-{user.pk}@erased.invalid", name="", password=make_password(None), is_active=False,
                is_staff=False, is_superuser=False, last_login=None, deleted_at=self.ledger.clock.now(),
            )  # fmt: skip
            user.groups.clear()
            user.user_permissions.clear()
        return forfeited
