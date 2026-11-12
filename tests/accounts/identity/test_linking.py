"""Unit under test: `accounts.identity.linking.LinkPolicy`, the rule for whether a provider sign-in may reach an
existing account (plan 5.5, D6).

Why: this one rule is the difference between "sign in with Google" and "anyone who can make a Google account with my
address is me". An email is matched for linking ONLY if its owner proved it (the source is `code`, `google` or
`microsoft`); an address nobody proved (legacy, staff-vouched, operator-made, never verified) is TAKEN OVER by the
first person who proves it, so a stranger's pre-made account cannot be a trap; a staff account is never linked to or
taken over; a closed account is never revived; and the same Google address belonging to a different Google person is
never merged. The policy is pure, so every row is a table test with plain objects.

Use cases:
- an address the provider does not call verified is refused, whatever else is true
- a link found by `(provider, subject)` signs in (the email may have changed), unless the account is closed, erased or
  staff
- a new person (no link, no account with that address) goes to the last step
- an account whose email the owner proved (`code`, `google`, `microsoft`) is linked to and signed in
- **every other source (`legacy`, `staff`, `operator`, empty) and an unverified account is taken over, never
  linked**: a parametrised test over every source value, so a new source added later fails until it is placed
- a staff or superuser account found by email is refused, whatever its source
- a closed (inactive) or erased account found by email is refused
- an account already linked to a DIFFERENT subject of this provider is refused, so a recycled address is not merged
"""

from types import SimpleNamespace

import pytest

from accounts.identity.linking import LinkDecision, LinkPolicy
from accounts.identity.provider import VerifiedIdentity
from accounts.models import User

POLICY = LinkPolicy()


def identity(verified=True):
    return VerifiedIdentity("google", "sub-1", "ada@example.com", verified, "Ada")


def account(source="code", verified=True, **flags):
    defaults = {"is_active": True, "is_staff": False, "is_superuser": False, "deleted_at": None}
    user = SimpleNamespace(**{**defaults, **flags})
    user.is_email_verified = verified
    user.email_verification_source = source if verified else ""
    user.email_proved_by_owner = verified and source in User.PROVED_BY_OWNER
    return user


def link(user):
    return SimpleNamespace(user=user)


def test_an_address_the_provider_does_not_call_verified_is_refused_whatever_else_is_true():
    for found in (None, account("code")):
        assert POLICY.decide(identity(False), None, found) is LinkDecision.REFUSE_UNVERIFIED_EMAIL
    assert POLICY.decide(identity(False), link(account()), None) is LinkDecision.REFUSE_UNVERIFIED_EMAIL


def test_a_link_found_by_subject_signs_in_even_when_the_email_has_changed():
    assert POLICY.decide(identity(), link(account()), None) is LinkDecision.SIGN_IN
    assert POLICY.decide(identity(), link(account("legacy")), account("code")) is LinkDecision.SIGN_IN  # the link wins


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ({"is_active": False}, LinkDecision.REFUSE_CLOSED),
        ({"deleted_at": "2026-01-01"}, LinkDecision.REFUSE_CLOSED),
        ({"is_staff": True}, LinkDecision.REFUSE_STAFF),
        ({"is_superuser": True}, LinkDecision.REFUSE_STAFF),
    ],
)
def test_a_link_to_a_closed_erased_or_staff_account_is_refused(flags, expected):
    assert POLICY.decide(identity(), link(account(**flags)), None) is expected


def test_a_new_person_goes_to_the_last_step():
    assert POLICY.decide(identity(), None, None) is LinkDecision.NEEDS_FINISH


@pytest.mark.parametrize("source", sorted(User.PROVED_BY_OWNER))
def test_an_account_whose_email_its_owner_proved_is_linked_to(source):
    assert POLICY.decide(identity(), None, account(source)) is LinkDecision.LINK_AND_SIGN_IN


@pytest.mark.parametrize("source", [s.value for s in User.VerificationSource if s.value not in User.PROVED_BY_OWNER])
def test_every_source_the_owner_did_not_prove_is_taken_over_never_linked(source):
    assert POLICY.decide(identity(), None, account(source)) is LinkDecision.TAKE_OVER


def test_an_unverified_account_is_taken_over_never_linked():
    assert POLICY.decide(identity(), None, account(verified=False)) is LinkDecision.TAKE_OVER


def test_the_sources_are_exactly_the_three_that_link_so_a_new_one_must_be_placed_on_purpose():
    assert User.PROVED_BY_OWNER == {"code", "google", "microsoft"}
    every = {s.value for s in User.VerificationSource}
    assert User.PROVED_BY_OWNER <= every and every - User.PROVED_BY_OWNER == {"staff", "operator", "legacy"}


@pytest.mark.parametrize("source", ["code", "google", "legacy", "staff", "operator"])
@pytest.mark.parametrize("flags", [{"is_staff": True}, {"is_superuser": True}])
def test_a_staff_account_found_by_email_is_refused_whatever_its_source(source, flags):
    assert POLICY.decide(identity(), None, account(source, **flags)) is LinkDecision.REFUSE_STAFF


@pytest.mark.parametrize("source", ["code", "legacy"])
def test_a_closed_or_erased_account_found_by_email_is_refused(source):
    assert POLICY.decide(identity(), None, account(source, is_active=False)) is LinkDecision.REFUSE_CLOSED
    assert POLICY.decide(identity(), None, account(source, deleted_at="2026-01-01")) is LinkDecision.REFUSE_CLOSED


def test_an_account_already_linked_to_a_different_subject_is_never_merged():
    proved = account("google")

    assert POLICY.decide(identity(), None, proved, email_owner_has_other_identity=True) is (
        LinkDecision.REFUSE_OTHER_IDENTITY
    )
    assert POLICY.decide(identity(), None, account("legacy"), True) is LinkDecision.REFUSE_OTHER_IDENTITY
