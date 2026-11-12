"""Unit under test: `accounts.tokens.RefreshTokens`, `accounts.identity.links.IdentityLinks` and
`AccountActivation.prove`, the three small parts of a password reset.

Why: a reset must end every session of the account and only that account's, must tell an account that signs in with
Google (no password to reset) from one that has no password yet (staff approved it: its first password comes from a
reset), and must count the reset as proof of the inbox only when the owner had not already proved it.

Use cases:
- `revoke_all` blacklists every refresh token of one account, counts only the newly revoked ones, leaves other accounts
  alone, and a second call revokes nothing
- a revoked token cannot be renewed
- an account "signs in only with a provider" when it has a linked identity and no usable password: not with a password
  too, and not with no identity (a staff-approved account)
- `prove` marks a legacy, staff-vouched, operator-made or never-verified account as verified by code and says so; an
  account the owner already proved is left as it was and `prove` says nothing changed
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from support.clock import FakeClock

from accounts.identity.links import IdentityLinks
from accounts.models import ExternalIdentity, User
from accounts.tokens import RefreshTokens
from accounts.verification.activation import AccountActivation

pytestmark = pytest.mark.django_db


def test_revoke_all_blacklists_every_token_of_one_account_and_only_that_one(user, other_user):
    mine = [RefreshToken.for_user(user) for _ in range(3)]
    theirs = RefreshToken.for_user(other_user)
    mine[0].blacklist()  # one was already revoked

    assert RefreshTokens.revoke_all(user) == 2  # only the newly revoked ones are counted

    assert BlacklistedToken.objects.filter(token__user=user).count() == 3
    assert not BlacklistedToken.objects.filter(token__user=other_user).exists()
    assert RefreshTokens.revoke_all(user) == 0
    assert OutstandingToken.objects.filter(user=other_user).count() == 1 and theirs


def test_a_revoked_token_cannot_be_renewed(user):
    token = str(RefreshToken.for_user(user))
    client = APIClient()
    client.cookies["lc_refresh"] = token
    assert client.post("/api/auth/refresh").status_code == 200

    RefreshTokens.revoke_all(user)

    stale = APIClient()
    stale.cookies["lc_refresh"] = token
    assert stale.post("/api/auth/refresh").status_code == 401


def test_an_account_signs_in_only_with_a_provider_when_it_has_an_identity_and_no_password(user):
    google = User.objects.create_user("g@example.com", password=None, name="G")
    approved = User.objects.create_user("approved@example.com", password=None, name="A")
    ExternalIdentity.objects.create(user=google, provider="google", subject="s-1")
    ExternalIdentity.objects.create(user=user, provider="google", subject="s-2")  # has a password too

    assert IdentityLinks.signs_in_only_with_a_provider(google)
    assert not IdentityLinks.signs_in_only_with_a_provider(user)  # a password as well
    assert not IdentityLinks.signs_in_only_with_a_provider(approved)  # no identity: its first password comes by a reset
    assert IdentityLinks.has_identity(user) and not IdentityLinks.has_identity(approved)


@pytest.mark.parametrize("source", ["legacy", "staff", "operator", ""])
def test_prove_makes_an_account_the_owner_did_not_prove_code_verified(source):
    clock = FakeClock()
    account = User.objects.create_user("a@example.com", password="x" * 12, name="A")
    if source:
        User.objects.filter(pk=account.pk).update(email_verified_at=clock.now(), email_verification_source=source)
        account.refresh_from_db()
    clock.advance(days=3)

    assert AccountActivation(clock).prove(account) is True

    account.refresh_from_db()
    assert account.email_verification_source == "code" and account.email_verified_at == clock.now()


@pytest.mark.parametrize("source", ["code", "google", "microsoft"])
def test_prove_leaves_an_account_the_owner_already_proved_alone(source):
    clock = FakeClock()
    account = User.objects.create_user("a@example.com", password="x" * 12, name="A")
    User.objects.filter(pk=account.pk).update(email_verified_at=clock.now(), email_verification_source=source)
    account.refresh_from_db()
    clock.advance(days=3)

    assert AccountActivation(clock).prove(account) is False

    account.refresh_from_db()
    assert account.email_verification_source == source and account.email_verified_at != clock.now()
