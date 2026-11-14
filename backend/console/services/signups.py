"""People waiting for a code (plan 10, D15): sign-ups that are not accounts yet.

Staff can send a new code, unlock an email that keeps killing its codes, and **approve** a stuck sign-up.
Approving makes the account from the pending row **with an unusable password**: the hash the person typed is
never copied, so approving gives nobody a way in. The person then signs in with Google, or chooses a password
with "Forgot password". Because approving vouches for someone nobody has proved, the reply says so, and staff
must type a reason that is kept in the change log.

The change log never holds an email address for a sign-up (it has no account to erase it with): it names the
pending row's id and the email's domain."""

from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.http import Http404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException, ValidationError

from accounts.emailrules.canonical import EmailCanonicalizer
from accounts.mail.tasks import MailQueue
from accounts.mail.templates import MailTemplates
from accounts.models import EmailLock, PendingSignup, User, VerificationCode
from accounts.verification.activation import AccountActivation
from accounts.verification.issuer import CodeIssuer
from accounts.verification.locks import EmailLocks
from console.audit import AuditTrail

REASON_MIN_LENGTH = 10

APPROVAL_NOTE = (
    "Confirm this person out of band first (a message from the address on file, or in person). They have no password "
    'yet: they sign in with Google, or choose a password with "Forgot password".'
)


class SignupRefused(APIException):
    status_code = status.HTTP_409_CONFLICT

    def __init__(self, code: str, detail: str):
        super().__init__(detail=detail, code=code)


class PendingSignups:
    REFUSALS = {
        "expired": "This sign-up has expired. The person has to register again.",
        "account_exists": "An account already has this email.",
        "not_locked": "This email is not locked and has no live code.",
    }

    def __init__(
        self,
        trail: AuditTrail,
        issuer: CodeIssuer | None = None,
        mail: MailQueue | None = None,
        templates: MailTemplates | None = None,
        activation: AccountActivation | None = None,
    ):
        self.trail = trail
        self.issuer = issuer or CodeIssuer()
        self.mail = mail or MailQueue()
        self.templates = templates or MailTemplates()
        self.activation = activation or AccountActivation()

    @staticmethod
    def queryset(search: str = ""):
        """Sign-ups still waiting, newest first, each with how many tries its live code has left and whether its
        email is locked: subqueries, so the list costs the same for three rows and for thirty."""
        live = VerificationCode.objects.filter(
            pending=OuterRef("pk"), consumed_at__isnull=True, invalidated_at__isnull=True
        )
        rows = PendingSignup.objects.filter(expires_at__gt=timezone.now()).annotate(
            code_tries=Subquery(live.values("attempts")[:1]),
            code_max_tries=Subquery(live.values("max_attempts")[:1]),
            code_expires_at=Subquery(live.values("expires_at")[:1]),
            locked_until=Subquery(
                EmailLock.objects.filter(email_canonical=OuterRef("email_canonical")).values("locked_until")[:1]
            ),
        )
        if search := search.strip():
            rows = rows.filter(email__icontains=search)
        return rows

    def resend(self, pending_id) -> dict:
        """A new code to the address the person gave. It works only in the browser that registered (its signup ticket),
        which the reply says."""
        with transaction.atomic():
            pending = self._live(pending_id, lock=True)
            issued = self.issuer.issue(VerificationCode.Purpose.SIGNUP, pending.email_canonical, pending=pending)
            self.mail.send(self.templates.signup_code(pending.email, issued.code, issued.minutes))
            self.trail.record(
                "signup.resend", "signup", pending.pk,
                before={"email_domain": self._domain(pending)}, after={"code_sent": True},
            )  # fmt: skip
        return {
            "sent": True,
            "note": (
                "A new code was sent. It works only in the browser that made the sign-up; "
                "if they have lost it, they register again."
            ),
        }

    def unlock(self, pending_id) -> dict:
        with transaction.atomic():
            pending = self._live(pending_id, lock=True)
            canonical = pending.email_canonical
            locked = EmailLocks().is_locked(canonical)
            live = VerificationCode.objects.filter(
                email_canonical=canonical, consumed_at__isnull=True, invalidated_at__isnull=True
            )
            had_live = live.exists()
            if not locked and not had_live:
                raise SignupRefused("not_locked", self.REFUSALS["not_locked"])
            EmailLocks().clear(canonical)
            live.update(invalidated_at=timezone.now())
            self.trail.record(
                "signup.unlock", "signup", pending.pk,
                before={"locked": locked, "live_codes": had_live, "email_domain": self._domain(pending)},
                after={"locked": False, "live_codes": False},
            )  # fmt: skip
        return {"unlocked": True, "note": "Now send a new code: the old one was cancelled."}

    def approve(self, pending_id, reason: str) -> dict:
        """Makes the account **with an unusable password**, verified by staff, and gives the signup credits once."""
        reason = (reason or "").strip()
        if len(reason) < REASON_MIN_LENGTH:
            raise ValidationError({"reason": [f"Say why, in at least {REASON_MIN_LENGTH} characters."]})
        with transaction.atomic():
            pending = self._live(pending_id, lock=True)
            if User.objects.filter(email_canonical=EmailCanonicalizer.of(pending.email)).exists():
                raise SignupRefused("account_exists", self.REFUSALS["account_exists"])
            domain, pending_key = self._domain(pending), pending.pk
            user = self.activation.create_approved(pending)
            self.trail.record(
                "signup.approved", "signup", pending_key,
                before={"email_domain": domain}, after={"learner_id": user.pk, "source": "staff", "reason": reason},
            )  # fmt: skip
            self.activation.announce(user)  # after the commit; the grant is keyed on the learner
        return {"learner_id": user.pk, "signs_in_with": "google_or_reset", "note": APPROVAL_NOTE}

    def _live(self, pending_id, lock: bool = False) -> PendingSignup:
        rows = PendingSignup.objects.select_for_update() if lock else PendingSignup.objects
        pending = rows.filter(pk=pending_id).first()
        if pending is None:
            raise Http404
        if pending.expires_at <= timezone.now():
            raise SignupRefused("expired", self.REFUSALS["expired"])
        return pending

    @staticmethod
    def _domain(pending: PendingSignup) -> str:
        return pending.email_canonical.rpartition("@")[2]
