"""A learner's sign-in verification, for support (plan 10, D15): see what happened, resend a code, unlock an email, and
mark an account verified by hand.

Every action is refused for the wrong state with a code a screen can say, is audited with the staff member and
(for the one that vouches for a person) a typed reason in the same transaction as the change, and changes only
what its name says. `mark_verified` makes the account verified with the source `staff` (someone vouched; the
owner did not prove the inbox) and announces it, so the signup credits come exactly once however often it is
pressed."""

from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError

from accounts.models import EmailLock, ExternalIdentity, OutboundMail, SignupRecord, User, VerificationCode
from accounts.verification.activation import AccountActivation
from accounts.verification.locks import EmailLocks
from accounts.verification.login import LoginVerification
from console.audit import AuditTrail

REASON_MIN_LENGTH = 10


class VerificationRefused(APIException):
    """An action that makes no sense for this account, as a code (`already_verified`, `account_closed`,
    `account_erased`, `nothing_to_unlock`)."""

    status_code = status.HTTP_409_CONFLICT

    def __init__(self, code: str, detail: str):
        super().__init__(detail=detail, code=code)


class LearnerVerification:
    REFUSALS = {
        "already_verified": "This account's email is already verified.",
        "account_closed": "This account is closed.",
        "account_erased": "This account has been erased.",
        "nothing_to_unlock": "This email is not locked and has no live code.",
    }

    def __init__(
        self, trail: AuditTrail, activation: AccountActivation | None = None, login: LoginVerification | None = None
    ):
        self.trail = trail
        self.activation = activation or AccountActivation()
        self.login = login or LoginVerification()

    # --- what staff see ---

    def panel(self, learner_id) -> dict:
        """Everything that explains why this person is stuck: the state, how they can sign in, the last five codes
        (never a code), the last five emails sent to them, the lock and where the account was made from."""
        user = self._user(learner_id)
        now = timezone.now()
        return {
            "learner": {"id": user.pk, "name": user.name, "email": user.email},
            "state": self._state(user),
            "sign_in_methods": self.methods(user),
            "identities": [
                {
                    "provider": i.provider,
                    "linked_at": i.created_at,
                    "last_sign_in_at": i.last_sign_in_at,
                    "hosted_domain": i.hosted_domain,
                }
                for i in ExternalIdentity.objects.filter(user=user).order_by("created_at")
            ],
            "codes": [self._code(c, now) for c in self._codes(user)[:5]],
            "mail": [
                {"kind": m.kind, "status": m.status, "error": m.error, "created_at": m.created_at, "sent_at": m.sent_at}
                for m in OutboundMail.objects.filter(to_email__iexact=user.email).order_by("-created_at", "-pk")[:5]
            ],
            "lock": self._lock(user, now),
            "signup_record": self._record(user),
        }

    @staticmethod
    def methods(user: User) -> list[str]:
        """How the person can sign in: `password` when the account has a usable one, and each linked provider."""
        found = ["password"] if user.has_usable_password() else []
        return found + [i.provider for i in ExternalIdentity.objects.filter(user=user).order_by("created_at")]

    # --- what staff can do ---

    def resend(self, learner_id) -> dict:
        """A fresh sign-in code to the learner's own address. Refused for a verified, closed or erased account."""
        with transaction.atomic():
            user = self._user(learner_id, lock=True)
            self._must_be_unverified(user)
            self.login.start(user)
            self.trail.record(
                "learner.verification_resent", "learner", user.pk,
                before={"email_verified": False}, after={"code_sent": True},
            )  # fmt: skip
        return self.panel(user.pk)

    def unlock(self, learner_id) -> dict:
        """Clears the email's lock and cancels its live codes, so the next try starts clean."""
        with transaction.atomic():
            user = self._user(learner_id, lock=True)
            self._must_be_open(user)
            canonical = user.email_canonical
            locked = EmailLocks().is_locked(canonical)
            live = VerificationCode.objects.filter(
                email_canonical=canonical, consumed_at__isnull=True, invalidated_at__isnull=True
            )
            had_live = live.exists()
            if not locked and not had_live:
                raise VerificationRefused("nothing_to_unlock", self.REFUSALS["nothing_to_unlock"])
            EmailLocks().clear(canonical)
            live.update(invalidated_at=timezone.now())
            self.trail.record(
                "learner.verification_unlocked", "learner", user.pk,
                before={"locked": locked, "live_codes": had_live}, after={"locked": False, "live_codes": False},
            )  # fmt: skip
        return self.panel(user.pk)

    def mark_verified(self, learner_id, reason: str) -> dict:
        """Verifies the account by hand with a typed reason, and announces it (the signup credits, once)."""
        reason = (reason or "").strip()
        if len(reason) < REASON_MIN_LENGTH:
            raise ValidationError({"reason": [f"Say why, in at least {REASON_MIN_LENGTH} characters."]})
        with transaction.atomic():
            user = self._user(learner_id, lock=True)  # two staff pressing it at once: the second finds it verified
            self._must_be_unverified(user)
            self.activation.verify_existing(user, User.VerificationSource.STAFF)
            self.trail.record(
                "learner.verification_marked", "learner", user.pk,
                before={"email_verified": False, "source": ""},
                after={"email_verified": True, "source": User.VerificationSource.STAFF, "reason": reason},
            )  # fmt: skip
            self.activation.announce(user)  # after the commit; the grant is keyed on the learner, so it is made once
        return self.panel(user.pk)

    # --- rules ---

    def _must_be_open(self, user: User) -> None:
        if user.deleted_at is not None:
            raise VerificationRefused("account_erased", self.REFUSALS["account_erased"])
        if not user.is_active:
            raise VerificationRefused("account_closed", self.REFUSALS["account_closed"])

    def _must_be_unverified(self, user: User) -> None:
        self._must_be_open(user)
        if user.is_email_verified:
            raise VerificationRefused("already_verified", self.REFUSALS["already_verified"])

    def _state(self, user: User) -> dict:
        open_ = user.deleted_at is None and user.is_active
        unverified = open_ and not user.is_email_verified
        return {
            "verified": user.is_email_verified,
            "verified_at": user.email_verified_at,
            "source": user.email_verification_source,
            "legacy": user.email_verification_source == User.VerificationSource.LEGACY,
            "closed": not user.is_active,
            "erased": user.deleted_at is not None,
            "can_resend": unverified,
            "can_mark_verified": unverified,
            "can_unlock": open_,
        }

    @staticmethod
    def _codes(user: User):
        from django.db.models import Q

        return VerificationCode.objects.filter(Q(email_canonical=user.email_canonical) | Q(user=user)).order_by(
            "-created_at"
        )

    @staticmethod
    def _code(code: VerificationCode, now) -> dict:
        if code.consumed_at:
            state = "used"
        elif code.invalidated_at:
            state = "dead" if code.attempts >= code.max_attempts else "cancelled"
        elif code.expires_at <= now:
            state = "expired"
        else:
            state = "live"
        return {  # never the code, and never its hash
            "purpose": code.purpose, "created_at": code.created_at, "expires_at": code.expires_at,
            "tries": code.attempts, "max_tries": code.max_attempts, "state": state,
        }  # fmt: skip

    @staticmethod
    def _lock(user: User, now) -> dict | None:
        lock = EmailLock.objects.filter(email_canonical=user.email_canonical).first()
        if lock is None or lock.locked_until is None or lock.locked_until <= now:
            return None
        return {"locked_until": lock.locked_until, "strikes": lock.strikes}

    @staticmethod
    def _record(user: User) -> dict | None:
        found = SignupRecord.objects.filter(user=user).first()
        if found is None:
            return None
        return {
            "ip": found.ip,
            "email_domain": found.email_domain,
            "method": found.method,
            "created_at": found.created_at,
        }

    @staticmethod
    def _user(learner_id, lock: bool = False) -> User:
        rows = User.objects.select_for_update() if lock else User.objects
        user = rows.filter(pk=learner_id).first()
        if user is None:
            raise Http404
        return user
