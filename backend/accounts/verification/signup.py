"""Sign-up with a code (plan 5.2, D4, D5, T19): **no account until the code is entered**.

`start` keeps a *pending sign-up* (name, the hash of the password, the zone, the terms the person agreed to) and mails
a code. `confirm` turns it into the account when the right code arrives **with the ticket of that row**; every other
outcome is the same "no". An address that already has an account is not told so: it is mailed a notice instead, and
the caller sees the same reply either way.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError, transaction

from ..clock import Clock, SystemClock
from ..dblock import DbLock
from ..emailrules.canonical import EmailCanonicalizer, MalformedEmail
from ..emailrules.policy import EmailPolicy
from ..mail.tasks import MailQueue
from ..mail.templates import MailTemplates
from ..models import PendingSignup, User, VerificationCode
from .activation import AccountActivation
from .checker import CodeChecker
from .config import VerificationSettings
from .issuer import CodeIssuer
from .ticket import SignupTicket


@dataclass(frozen=True)
class SignupRequest:
    """What the person typed (the password already hashed) and what they agreed to."""

    email: str
    name: str
    password_hash: str
    timezone: str
    terms_version: str
    terms_accepted_at: datetime


@dataclass(frozen=True)
class Started:
    """What the caller needs for the reply: the ticket to hand out, which is a real pending row's id, or, for an address
    that already has an account, one that matches nothing."""

    ticket: str


class SignupVerification:
    def __init__(
        self,
        policy: EmailPolicy | None = None,
        issuer: CodeIssuer | None = None,
        checker: CodeChecker | None = None,
        activation: AccountActivation | None = None,
        mail: MailQueue | None = None,
        templates: MailTemplates | None = None,
        tickets: SignupTicket | None = None,
        clock: Clock | None = None,
        settings: VerificationSettings | None = None,
    ):
        self.clock = clock or SystemClock()
        self.policy = policy or EmailPolicy()
        self.issuer = issuer or CodeIssuer(clock=self.clock, settings=settings)
        self.checker = checker or CodeChecker(clock=self.clock)
        self.activation = activation or AccountActivation(self.clock)
        self.mail = mail or MailQueue()
        self.templates = templates or MailTemplates()
        self.tickets = tickets or SignupTicket(settings)
        self._settings = settings

    @property
    def settings(self) -> VerificationSettings:
        return self._settings or VerificationSettings.from_settings()

    def start(self, request: SignupRequest, ip: str | None) -> Started:
        """Keeps the sign-up and mails the code, or mails the owner of the address a notice. Raises `EmailRefused` for
        an address the policy refuses (the same for known and unknown ones, so it tells nothing)."""
        canonical = self.policy.check(request.email)
        owner = User.objects.filter(email_canonical=canonical).first()
        if owner is not None:
            self.mail.send(
                self.templates.owner_notice(owner.email)
            )  # to the address the account has, never the typed one
            return Started(self.tickets.decoy())
        now = self.clock.now()
        with transaction.atomic():
            DbLock.acquire(f"signup:{canonical}")  # two registers for one inbox take turns; the later one wins
            PendingSignup.objects.filter(email_canonical=canonical).delete()  # its codes go with it, its ticket is dead
            pending = PendingSignup.objects.create(
                email=request.email,
                email_canonical=canonical,
                name=request.name,
                password_hash=request.password_hash,
                timezone=request.timezone,
                terms_accepted_at=request.terms_accepted_at,
                terms_version=request.terms_version,
                created_at=now,
                expires_at=now + self.settings.pending_ttl,
            )
            issued = self.issuer.issue(VerificationCode.Purpose.SIGNUP, canonical, pending=pending, ip=ip)
            self.mail.send(self.templates.signup_code(pending.email, issued.code, issued.minutes))
        return Started(self.tickets.issue(pending.pk))

    def confirm(self, email: str, code: str, ticket: str | None, ip: str | None = None) -> User | None:
        """The account, or None. None is the one answer for every failure: no ticket, a ticket of another row, an
        unknown email, a wrong, expired, used or dead code, a locked email."""
        pending_id = self.tickets.read(ticket)
        canonical = self._canonical(email)
        if pending_id is None or canonical is None:
            return None  # no try is spent: a stranger without the ticket cannot burn the owner's tries
        try:
            with transaction.atomic():
                pending = self._live_pending(canonical, pending_id, lock=True)
                if pending is None:
                    return None
                if not self.checker.check(VerificationCode.Purpose.SIGNUP, canonical, code).ok:
                    return None  # committed: the counted try stays
                try:
                    with transaction.atomic():
                        user = self.activation.create_from_signup(pending, ip)
                except IntegrityError:
                    return None  # an account took the address between the sign-up and now
        except IntegrityError:
            return None
        self.activation.announce(user)
        return user

    def resend(self, email: str, ticket: str | None, ip: str | None = None) -> bool:
        """A new code for this browser's own pending sign-up. Without its ticket nothing is sent (so a stranger cannot
        cancel someone's live code). True when a code was queued."""
        pending_id = self.tickets.read(ticket)
        canonical = self._canonical(email)
        if pending_id is None or canonical is None:
            return False
        with transaction.atomic():
            pending = self._live_pending(canonical, pending_id, lock=True)
            if pending is None:
                return False
            issued = self.issuer.issue(VerificationCode.Purpose.SIGNUP, canonical, pending=pending, ip=ip)
            self.mail.send(self.templates.signup_code(pending.email, issued.code, issued.minutes))
        return True

    def _live_pending(self, canonical: str, pending_id: uuid.UUID, lock: bool = False) -> PendingSignup | None:
        rows = PendingSignup.objects.select_for_update() if lock else PendingSignup.objects
        return rows.filter(pk=pending_id, email_canonical=canonical, expires_at__gt=self.clock.now()).first()

    @staticmethod
    def _canonical(email: str) -> str | None:
        try:
            return EmailCanonicalizer.of(email)
        except MalformedEmail:
            return None
