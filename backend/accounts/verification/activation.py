"""Making an account ready (plan T15): the one class that turns a proved email into a `User` and a grant.

`account_ready` is sent **only here**. The signup credits hang from it (`credits.signals`), so a new way to prove an
email (Google, later) calls this and cannot forget the grant or send it twice. Creating the account is part of the
caller's transaction; announcing it is a separate step the caller takes after that transaction commits."""

import logging

from django.db import transaction

from ..abuse.records import SignupRecords
from ..clock import Clock, SystemClock
from ..emailrules.canonical import EmailCanonicalizer
from ..identity.provider import VerifiedIdentity
from ..models import ExternalIdentity, PendingSignup, SignupRecord, User
from ..signals import account_ready
from ..timezones import ProfileTimezone, TimeZoneNames
from ..tokens import RefreshTokens

logger = logging.getLogger(__name__)


class AccountActivation:
    def __init__(self, clock: Clock | None = None):
        self.clock = clock or SystemClock()

    def create_from_signup(self, pending: PendingSignup, ip: str | None) -> User:
        """The account a pending sign-up becomes, verified by code. The password is the hash the person chose at
        sign-up; the pending row is deleted. Raises `IntegrityError` if an account has taken the address meanwhile."""
        user = User(
            email=pending.email,
            name=pending.name,
            password=pending.password_hash,
            terms_accepted_at=pending.terms_accepted_at,
            terms_version=pending.terms_version,
            email_verified_at=self.clock.now(),
            email_verification_source=User.VerificationSource.CODE,
        )
        user.save()  # the profile is made by the post_save receiver
        if TimeZoneNames.is_valid(pending.timezone):  # a name no zone database knows must not stop anyone signing up
            ProfileTimezone().apply(user.profile, pending.timezone)
            user.profile.save(update_fields=["timezone", "timezone_changed_at", "updated_at"])
        SignupRecords(self.clock).record(user, ip, SignupRecord.Method.CODE)
        pending.delete()
        return user

    def create_approved(self, pending: PendingSignup) -> User:
        """The account a staff member approves from a pending sign-up (plan S2, D15), **with an unusable password**: the
        hash the person typed at sign-up is never copied, so approving gives nobody a way in. The person signs in with
        Google or chooses a password by a reset. Verified by staff (`staff`: someone vouched, the owner did not prove
        it)."""
        user = User(
            email=pending.email,
            name=pending.name,
            terms_accepted_at=pending.terms_accepted_at,
            terms_version=pending.terms_version,
            email_verified_at=self.clock.now(),
            email_verification_source=User.VerificationSource.STAFF,
        )
        user.set_unusable_password()
        user.save()
        if TimeZoneNames.is_valid(pending.timezone):
            ProfileTimezone().apply(user.profile, pending.timezone)
            user.profile.save(update_fields=["timezone", "timezone_changed_at", "updated_at"])
        SignupRecords(self.clock).record(user, None, SignupRecord.Method.STAFF)
        pending.delete()
        return user

    def create_from_identity(self, identity: VerifiedIdentity, name: str, zone: str, ip: str | None) -> User:
        """The account a verified Google identity becomes, once the person has given their name and agreed to the
        terms (the "one last step"). It has **no password** (they sign in with the provider, or choose one by a reset),
        the email as the provider gave it, verified by the provider, the identity linked, and a pending sign-up for the
        same address, if any, gone. Raises `IntegrityError` if an account has taken the address meanwhile."""
        user = User(
            email=User.objects.normalize_email(identity.email),
            name=name,
            terms_accepted_at=self.clock.now(),
            terms_version=User.TERMS_VERSION,
            email_verified_at=self.clock.now(),
            email_verification_source=identity.source,
        )
        user.set_unusable_password()
        user.save()  # the profile is made by the post_save receiver
        if TimeZoneNames.is_valid(zone):
            ProfileTimezone().apply(user.profile, zone)
            user.profile.save(update_fields=["timezone", "timezone_changed_at", "updated_at"])
        self.link(user, identity)
        SignupRecords(self.clock).record(user, ip, identity.source)
        PendingSignup.objects.filter(email_canonical=EmailCanonicalizer.of(identity.email)).delete()
        return user

    def link(self, user: User, identity: VerifiedIdentity) -> ExternalIdentity:
        """Records that this provider identity is this account's sign-in."""
        return ExternalIdentity.objects.create(
            user=user, provider=identity.provider, subject=identity.subject, email_at_link=identity.email,
            hosted_domain=identity.hosted_domain, created_at=self.clock.now(), last_sign_in_at=self.clock.now(),
        )  # fmt: skip

    def take_over(self, user: User, identity: VerifiedIdentity) -> None:
        """The person who just signed in with a provider has proved the inbox of an account **nobody else proved** (a
        legacy, staff-vouched, operator-made or never-verified one): its password is made unusable, every session ends,
        the email is verified by the provider and the identity is linked. The caller announces the account (its credits,
        once)."""
        user.set_unusable_password()
        user.email_verified_at, user.email_verification_source = self.clock.now(), identity.source
        user.save(update_fields=["password", "email_verified_at", "email_verification_source"])
        RefreshTokens.revoke_all(user)
        self.link(user, identity)

    def verify_existing(self, user: User, source: str) -> bool:
        """Marks an existing account's email as proved by `source`. False when it already was (nothing changes)."""
        if user.is_email_verified:
            return False
        User.objects.filter(pk=user.pk, email_verified_at__isnull=True).update(
            email_verified_at=self.clock.now(), email_verification_source=source
        )
        user.refresh_from_db(fields=["email_verified_at", "email_verification_source"])
        return True

    def prove(self, user: User) -> bool:
        """The owner of the inbox has just shown they read it (a reset code came back): marks the email verified by code
        unless it was already proved by its owner. This turns a legacy, staff-vouched, operator-made or never-verified
        account into a code-verified one. True when something changed (the caller then announces the account)."""
        if user.email_proved_by_owner:
            return False
        User.objects.filter(pk=user.pk).update(
            email_verified_at=self.clock.now(),
            email_verification_source=User.VerificationSource.CODE,
        )
        user.refresh_from_db(fields=["email_verified_at", "email_verification_source"])
        return True

    @classmethod
    def announce(cls, user: User) -> None:
        """Tell the rest of the app an account is ready to use, **after the account is committed**: right away when no
        transaction is open, otherwise when the outermost one commits (and never if it rolls back). So no receiver,
        and no grant, ever runs for an account that does not exist, and a receiver that makes the database fail cannot
        take the caller's transaction, and the account with it, down."""
        transaction.on_commit(lambda: cls._send(user))

    @staticmethod
    def _send(user: User) -> None:
        """A receiver that fails is logged and cannot undo the account: the person exists, and what the receiver does
        (the signup credits) can be run again for them."""
        for receiver, outcome in account_ready.send_robust(sender=User, user=user):
            if isinstance(outcome, Exception):
                logger.error("account_ready receiver %r failed for user %s", receiver, user.pk, exc_info=outcome)
