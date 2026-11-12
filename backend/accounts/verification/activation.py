"""Making an account ready (plan T15): the one class that turns a proved email into a `User` and a grant.

`account_ready` is sent **only here**. The signup credits hang from it (`credits.signals`), so a new way to prove an
email (Google, later) calls this and cannot forget the grant or send it twice. Creating the account is part of the
caller's transaction; announcing it is a separate step the caller takes after that transaction commits."""

import logging

from django.db import transaction

from ..clock import Clock, SystemClock
from ..models import PendingSignup, SignupRecord, User
from ..signals import account_ready
from ..timezones import ProfileTimezone, TimeZoneNames

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
        SignupRecord.objects.create(
            user=user,
            ip=ip or None,
            email_domain=user.email_canonical.rpartition("@")[2],
            method=SignupRecord.Method.CODE,
            created_at=self.clock.now(),
        )
        pending.delete()
        return user

    def verify_existing(self, user: User, source: str) -> bool:
        """Marks an existing account's email as proved by `source`. False when it already was (nothing changes)."""
        if user.is_email_verified:
            return False
        User.objects.filter(pk=user.pk, email_verified_at__isnull=True).update(
            email_verified_at=self.clock.now(), email_verification_source=source
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
