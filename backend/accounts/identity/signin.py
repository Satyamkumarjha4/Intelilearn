"""Sign in with a provider, end to end (plan 6.1, 5.2): the Facade the three views call.

`start` makes the ticket and the address to send the person to. `callback` turns what the provider sent back into one
of: a signed-in account, "one last step" (a new person: nothing is created yet, so no account and no credits), or a
refusal with the code the sign-in page shows. `finish` is that last step: the name and the terms, then the account, the
link and the grant.
Every decision about an existing account is `LinkPolicy`'s; this class looks things up, asks it, and does what it says.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from django.db import IntegrityError, transaction

from ..clock import Clock, SystemClock
from ..dblock import DbLock
from ..emailrules.canonical import EmailCanonicalizer, MalformedEmail
from ..mail.tasks import MailQueue
from ..mail.templates import MailTemplates
from ..models import ExternalIdentity, User
from ..redirect import RedirectPolicy
from ..verification.activation import AccountActivation
from .linking import LinkDecision, LinkPolicy
from .provider import ProviderError, VerifiedIdentity
from .registry import IdentityProviders
from .state import FinishState, FinishTicket, OAuthState

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StartResult:
    url: str
    cookie: str


@dataclass(frozen=True)
class SignInResult:
    """What the callback decided. `kind` is `signed_in` (`user`), `finish` (`finish_cookie`) or `error` (`error`)."""

    kind: str
    next: str = RedirectPolicy.DEFAULT
    user: User | None = None
    finish_cookie: str | None = None
    error: str | None = None


class FinishRefused(Exception):
    """The last step cannot be taken. `code` is `finish_expired` (no or old ticket) or `invalid` (the form)."""

    def __init__(self, code: str, fields: dict | None = None):
        super().__init__(code)
        self.code, self.fields = code, fields or {}


class OAuthSignIn:
    DECISION_ERRORS = {
        LinkDecision.REFUSE_UNVERIFIED_EMAIL: "email_not_verified",
        LinkDecision.REFUSE_CLOSED: "account_closed",
        LinkDecision.REFUSE_STAFF: "sign_in_failed",  # staff sign in with a password; the words give nothing away
        LinkDecision.REFUSE_OTHER_IDENTITY: "sign_in_failed",
    }
    CONSENT_MESSAGE = "Please confirm to continue."

    def __init__(
        self,
        providers: IdentityProviders | None = None,
        state: OAuthState | None = None,
        finish_state: FinishState | None = None,
        policy: LinkPolicy | None = None,
        activation: AccountActivation | None = None,
        clock: Clock | None = None,
        mail: MailQueue | None = None,
        templates: MailTemplates | None = None,
    ):
        self.clock = clock or SystemClock()
        self.mail = mail or MailQueue()
        self.templates = templates or MailTemplates()
        self.providers = providers or IdentityProviders()
        self.state = state or OAuthState()
        self.finish_state = finish_state or FinishState()
        self.policy = policy or LinkPolicy()
        self.activation = activation or AccountActivation(self.clock)

    # --- the three steps ---

    def start(
        self, provider_key: str, next_value: object, options: Mapping[str, str], redirect_uri: str
    ) -> StartResult:
        """Raises `ProviderError("provider_off")` for a provider that is not on."""
        provider = self.providers.get(provider_key)
        if provider is None:
            raise ProviderError("provider_off", provider_key[:20])
        ticket = self.state.issue(provider_key, next_value)
        return StartResult(provider.start(ticket, redirect_uri, options), self.state.seal(ticket))

    def callback(
        self, provider_key: str, params: Mapping[str, str], cookie: str | None, redirect_uri: str
    ) -> SignInResult:
        provider = self.providers.get(provider_key)
        if provider is None:
            return SignInResult("error", error="provider_off")
        try:
            ticket = self.state.check(cookie, params.get("state"), provider_key)
        except ProviderError as refused:
            return SignInResult("error", error=refused.code)
        try:
            identity = provider.complete(params, ticket, redirect_uri)
        except ProviderError as refused:
            logger.warning("%s sign-in refused: %s", provider_key, refused.detail or refused.code)
            return SignInResult("error", next=ticket.next, error=refused.code)
        return self._resolve(identity, ticket.next)

    def finish(self, cookie: str | None, name: str, accept_terms: object, zone: str, ip: str | None) -> SignInResult:
        """The last step for a new person. Raises `FinishRefused`."""
        ticket = self.finish_state.read(cookie)
        if ticket is None:
            raise FinishRefused("finish_expired")
        problems = {}
        if accept_terms is not True:
            problems["accept_terms"] = [self.CONSENT_MESSAGE]
        if not name.strip():
            problems["name"] = ["Tell us your name."]
        if problems:
            raise FinishRefused("invalid", problems)
        return self._resolve(ticket.identity, ticket.next, create=(name.strip()[:150], zone, ip))

    def pending_identity(self, cookie: str | None) -> FinishTicket | None:
        """Who is waiting at the last step (for the form to show), or None with no live ticket."""
        return self.finish_state.read(cookie)

    # --- deciding and doing ---

    def _resolve(self, identity: VerifiedIdentity, next_value: str, create: tuple | None = None) -> SignInResult:
        """Looks the person up, asks `LinkPolicy`, and does what it says. With `create` (the last step) a new person
        becomes an account; without it a new person is sent to the last step. The lookups and the writes sit behind a
        lock on the identity and on the email, so two simultaneous callbacks for one new person make one account."""
        try:
            canonical = EmailCanonicalizer.of(identity.email)
        except MalformedEmail:
            return SignInResult("error", next=next_value, error="sign_in_failed")
        announce: User | None = None
        try:
            with transaction.atomic():
                DbLock.acquire(f"identity:{identity.provider}:{identity.subject}")
                DbLock.acquire(f"signup:{canonical}")
                by_subject = (
                    ExternalIdentity.objects.select_related("user")
                    .filter(provider=identity.provider, subject=identity.subject)
                    .first()
                )
                by_email = User.objects.filter(email_canonical=canonical).first()
                other = (
                    by_email is not None
                    and ExternalIdentity.objects.filter(user=by_email, provider=identity.provider)
                    .exclude(subject=identity.subject)
                    .exists()
                )
                decision = self.policy.decide(identity, by_subject, by_email, other)
                result, announce = self._act(decision, identity, by_subject, by_email, next_value, create)
        except IntegrityError:
            logger.warning("%s sign-in lost a race on the unique rules", identity.provider)
            return SignInResult("error", next=next_value, error="sign_in_failed")
        if announce is not None:
            self.activation.announce(announce)
        return result

    def _act(self, decision, identity, by_subject, by_email, next_value, create) -> tuple[SignInResult, User | None]:
        if decision in self.DECISION_ERRORS:
            return SignInResult("error", next=next_value, error=self.DECISION_ERRORS[decision]), None
        if decision is LinkDecision.SIGN_IN:
            ExternalIdentity.objects.filter(pk=by_subject.pk).update(last_sign_in_at=self.clock.now())
            return SignInResult("signed_in", next_value, user=by_subject.user), None
        if decision is LinkDecision.LINK_AND_SIGN_IN:
            self.activation.link(by_email, identity)
            return SignInResult("signed_in", next_value, user=by_email), None
        if decision is LinkDecision.TAKE_OVER:
            self.activation.take_over(by_email, identity)
            # Tell the address the account has (never the one the provider named): its password just stopped working.
            self.mail.send(self.templates.takeover_notice(by_email.email))
            return SignInResult("signed_in", next_value, user=by_email), by_email  # announced: the grant is idempotent
        # NEEDS_FINISH: a new person. Nothing exists until they take the last step.
        if create is None:
            cookie = self.finish_state.seal(FinishTicket(identity, next_value))
            return SignInResult("finish", next_value, finish_cookie=cookie), None
        name, zone, ip = create
        user = self.activation.create_from_identity(identity, name, zone, ip)
        return SignInResult("signed_in", next_value, user=user), user
