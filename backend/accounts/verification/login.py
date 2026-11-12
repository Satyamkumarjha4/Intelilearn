"""Finishing a sign-in for an account whose email was never proved (plan 5.2): a legacy or hand-made account.

The password was right but `email_verified_at` is empty, so a code goes to the address and the account is verified when
it comes back. There is no ticket here: the code only exists because the password was right, and it goes to the
account's own inbox. A wrong password never reaches this class."""

from django.db import transaction

from ..clock import Clock, SystemClock
from ..emailrules.canonical import EmailCanonicalizer, MalformedEmail
from ..mail.tasks import MailQueue
from ..mail.templates import MailTemplates
from ..models import User, VerificationCode
from .activation import AccountActivation
from .checker import CodeChecker
from .issuer import CodeIssuer


class LoginVerification:
    def __init__(
        self,
        issuer: CodeIssuer | None = None,
        checker: CodeChecker | None = None,
        activation: AccountActivation | None = None,
        mail: MailQueue | None = None,
        templates: MailTemplates | None = None,
        clock: Clock | None = None,
    ):
        self.clock = clock or SystemClock()
        self.issuer = issuer or CodeIssuer(clock=self.clock)
        self.checker = checker or CodeChecker(clock=self.clock)
        self.activation = activation or AccountActivation(self.clock)
        self.mail = mail or MailQueue()
        self.templates = templates or MailTemplates()

    def start(self, user: User, ip: str | None = None) -> None:
        """Mails a login code to the account's own address (as stored, which is the address the owner typed)."""
        with transaction.atomic():
            issued = self.issuer.issue(VerificationCode.Purpose.LOGIN, user.email_canonical, user=user, ip=ip)
            self.mail.send(self.templates.login_code(user.email, issued.code, issued.minutes))

    def resend(self, email: str, ip: str | None = None) -> bool:
        """A new code for an active, unverified account with this address; nothing for any other address (the caller
        answers the same either way). True when a code was queued."""
        user = self._unverified(email)
        if user is None:
            return False
        self.start(user, ip)
        return True

    def confirm(self, email: str, code: str) -> User | None:
        """The account, now verified by code, or None for every failure."""
        user = self._unverified(email)
        if user is None:
            return None
        with transaction.atomic():
            if not self.checker.check(VerificationCode.Purpose.LOGIN, user.email_canonical, code).ok:
                return None  # committed: the counted try stays
            self.activation.verify_existing(user, User.VerificationSource.CODE)
        self.activation.announce(user)
        return user

    @staticmethod
    def _unverified(email: str) -> User | None:
        try:
            canonical = EmailCanonicalizer.of(email)
        except MalformedEmail:
            return None
        return User.objects.filter(email_canonical=canonical, is_active=True, email_verified_at__isnull=True).first()
