"""Deleting a learner's data from the console (credits plan P5; phase 10.9 follow-up).

`LearnerErasure.preview` says what erasing an account would do and whether it is allowed; `erase` does it, after the
person at the keyboard has typed the account's email. The work is `credits.erasure.AccountErasure`, which anonymises the
account in place, deletes everything the learner made and every trace of their sign-in, and writes off their credits.
This class adds the rules that belong to the console: your own account and staff accounts are never erased from here, an
account already erased is said to be, and the change-log entry (counts and the learner's id, never a name or an
email) is written in the same transaction as the anonymising.
"""

from collections.abc import Callable

from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError

from accounts.models import User
from console.audit import AuditTrail
from credits.erasure import AccountErasure, AccountTraces
from credits.ledger import Ledger
from credits.models import CreditHold, CreditTransaction, PlanPurchase
from lessons.models import Lesson
from payments.models import PaymentOrder
from quizzes.models import QuickQuiz


class ErasureRefused(APIException):
    """An account that must not be erased from here, said as a code (`cannot_erase_self`, `staff_account`,
    `already_erased`)."""

    status_code = status.HTTP_409_CONFLICT

    def __init__(self, code: str, detail: str):
        super().__init__(detail=detail, code=code)


class LearnerErasure:
    REFUSALS = {
        "cannot_erase_self": "You cannot erase your own account from the console.",
        "staff_account": "This is a staff account. Remove its staff access in the Django admin first.",
        "already_erased": "This account has already been erased.",
    }

    def __init__(self, trail: AuditTrail, erasure_factory: Callable[[AuditTrail], AccountErasure] | None = None):
        self.trail = trail
        self.erasure_factory = erasure_factory or (lambda trail: AccountErasure(trail=trail))

    def preview(self, learner_id) -> dict:
        """What erasing would remove and what would stay, and why it is not allowed if it is not. Writes nothing."""
        user = self._user(learner_id)
        held = CreditHold.objects.filter(user=user, status=CreditHold.Status.HELD)
        traces = AccountTraces(user).counts()
        ledger = Ledger()
        return {
            "learner": {"id": user.pk, "name": user.name, "email": user.email},
            "erased": user.deleted_at is not None,
            "blocked": self._blocked(user),
            "lessons": Lesson.objects.filter(owner=user).count(),
            "quizzes": QuickQuiz.objects.filter(owner=user).count(),
            "open_reserves": held.count(),
            "credits_to_forfeit": ledger.balance(user) + sum(hold.amount for hold in held),
            "refresh_tokens": traces["tokens"],
            "sessions": traces["sessions"],
            "ledger_rows_kept": CreditTransaction.objects.filter(user=user).count(),
            "purchases_kept": PlanPurchase.objects.filter(user=user).count(),
            "orders_kept": PaymentOrder.objects.filter(user=user).count(),
        }

    def erase(self, learner_id, confirm_email: str, actor: User) -> dict:
        """Erase the account if the email typed is its own. Raises `ErasureRefused` (409) or `ValidationError` (400)."""
        user = self._user(learner_id)
        if reason := self._blocked(user, actor):
            raise ErasureRefused(reason, self.REFUSALS[reason])
        if (confirm_email or "").strip().lower() != user.email.lower():
            raise ValidationError({"confirm_email": ["Type the account's email exactly to confirm."]})
        report = self.erasure_factory(self.trail).erase(user)
        return {
            "learner": user.pk,
            "erased": True,
            "lessons": report.lessons,
            "quizzes": report.quizzes,
            "open_reserves_released": report.released_holds,
            "credits_forfeited": report.forfeited,
            "refresh_tokens": report.tokens,
            "sessions": report.sessions,
            "admin_log_rows": report.admin_log,
            "change_log_entries_cleaned": report.audit_scrubbed,
        }

    def _blocked(self, user: User, actor: User | None = None) -> str:
        actor = actor or self.trail.actor
        if user.deleted_at is not None:
            return "already_erased"
        if user.pk == actor.pk:
            return "cannot_erase_self"
        if user.is_staff or user.is_superuser:
            return "staff_account"
        return ""

    @staticmethod
    def _user(learner_id) -> User:
        user = User.objects.filter(pk=learner_id).first()
        if user is None:
            raise Http404
        return user
