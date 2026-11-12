"""Whether a sign-in with a provider may reach an existing account (plan 5.5, D6): the one rule that matters.

An email is matched for linking **only if its owner proved it**: the account's source is `code`, `google` or
`microsoft`. `legacy` (never proved), `staff` (someone vouched), `operator` and an unverified account are never matched:
for those the person who has just signed in with the provider, and so proved the inbox, **takes the account over** (its
password is made unusable and its sessions end), because nobody else has proved it. A staff account is never linked to
or taken over: it signs in with its password. `LinkPolicy` is pure: it is given what the lookups found and returns one
decision."""

from enum import Enum

from ..models import ExternalIdentity, User
from .provider import VerifiedIdentity


class LinkDecision(Enum):
    REFUSE_UNVERIFIED_EMAIL = "refuse_unverified_email"
    SIGN_IN = "sign_in"
    REFUSE_CLOSED = "refuse_closed"
    REFUSE_STAFF = "refuse_staff"
    REFUSE_OTHER_IDENTITY = "refuse_other_identity"
    LINK_AND_SIGN_IN = "link_and_sign_in"
    TAKE_OVER = "take_over"
    NEEDS_FINISH = "needs_finish"


class LinkPolicy:
    def decide(
        self,
        identity: VerifiedIdentity,
        by_subject: ExternalIdentity | None,
        by_email: User | None,
        email_owner_has_other_identity: bool = False,
    ) -> LinkDecision:
        """`by_subject`: the link found by `(provider, subject)`; `by_email`: the account found by canonical email;
        `email_owner_has_other_identity`: that account is already linked to a **different** subject of this provider."""
        if not identity.email_verified:
            return LinkDecision.REFUSE_UNVERIFIED_EMAIL
        if by_subject is not None:
            return self._for_account(
                by_subject.user, LinkDecision.SIGN_IN
            )  # the link is the key: the email may have changed
        if by_email is None:
            return LinkDecision.NEEDS_FINISH
        if email_owner_has_other_identity:
            # A different Google person with this address (a recycled work or school address): never merge them.
            return LinkDecision.REFUSE_OTHER_IDENTITY
        proved = by_email.email_proved_by_owner
        return self._for_account(by_email, LinkDecision.LINK_AND_SIGN_IN if proved else LinkDecision.TAKE_OVER)

    @staticmethod
    def _for_account(user: User, allowed: LinkDecision) -> LinkDecision:
        if not user.is_active or user.deleted_at is not None:
            return LinkDecision.REFUSE_CLOSED
        if user.is_staff or user.is_superuser:
            return LinkDecision.REFUSE_STAFF
        return allowed
