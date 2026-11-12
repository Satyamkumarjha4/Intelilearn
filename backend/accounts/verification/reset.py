"""Choosing a new password with a code (plan 5.8, D11): the same codes, limits and one-answer rules as sign-up.

`start` mails a reset code **only** to an active account that can use one; for every other address (unknown, closed,
an address that only has a pending sign-up) it does nothing, and the caller's reply is the same. An account that signs
in with Google and has no password is mailed "sign in with Google" instead. `confirm` checks the code, sets the
password, ends every older session, and counts the reset as proof of the inbox. An account with no usable password and
no linked identity (one staff approved) gets its **first** password this way.
"""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction

from ..clock import Clock, SystemClock
from ..emailrules.canonical import EmailCanonicalizer, MalformedEmail
from ..identity.links import IdentityLinks
from ..mail.tasks import MailQueue
from ..mail.templates import MailTemplates
from ..models import User, VerificationCode
from ..tokens import RefreshTokens
from .activation import AccountActivation
from .checker import CodeChecker
from .issuer import CodeIssuer


class WeakPassword(Exception):
    """The new password does not pass the password rules. `messages` are what the person reads."""

    def __init__(self, messages: list[str]):
        super().__init__("; ".join(messages))
        self.messages = messages


class PasswordReset:
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

    @staticmethod
    def check_password(new_password: str, email: str) -> None:
        """Raises `WeakPassword` if the password breaks the rules. It is judged against the address that was **typed**,
        never the account's name: a rule that behaved differently for a real account would tell whether one exists."""
        try:
            validate_password(new_password, user=User(email=email))
        except DjangoValidationError as error:
            raise WeakPassword(list(error.messages)) from error

    def start(self, email: str, ip: str | None = None) -> bool:
        """Mails a reset code, or the "sign in with Google" notice, to the account that has this address. True when
        something was mailed. Nothing at all for any other address (the caller answers the same either way)."""
        user = self._account(email)
        if user is None:
            return False
        if IdentityLinks.signs_in_only_with_a_provider(user):
            self.mail.send(self.templates.use_google_notice(user.email))
            return True
        with transaction.atomic():
            issued = self.issuer.issue(VerificationCode.Purpose.RESET, user.email_canonical, user=user, ip=ip)
            self.mail.send(self.templates.reset_code(user.email, issued.code, issued.minutes))
        return True

    def confirm(self, email: str, code: str, new_password: str) -> User | None:
        """The account with its new password, or None for every failure (a wrong, expired, used or dead code, a locked
        email, an address that has no account, an account that only signs in with a provider). Call `check_password`
        first so a weak password does not spend a try."""
        user = self._account(email)
        if user is None or IdentityLinks.signs_in_only_with_a_provider(user):
            return None
        with transaction.atomic():
            if not self.checker.check(VerificationCode.Purpose.RESET, user.email_canonical, code).ok:
                return None  # committed: the counted try stays
            user.set_password(new_password)
            user.save(update_fields=["password"])
            RefreshTokens.revoke_all(user)
            changed = self.activation.prove(user)
        if changed:
            self.activation.announce(user)
        return user

    @staticmethod
    def _account(email: str) -> User | None:
        """The active account with this address, or None: an unknown address, a closed or erased account and an address
        that has only a pending sign-up are all "no account"."""
        try:
            canonical = EmailCanonicalizer.of(email)
        except MalformedEmail:
            return None
        return User.objects.filter(email_canonical=canonical, is_active=True).first()
