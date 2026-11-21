"""Unit under test: `core.audit.accounts`: how a persona's account, and its profile, come to exist.

Why: a persona must be what a real learner is (verified address, signup record, a profile, the signup credits once),
or the audit's findings are about the seed, not the app. And making the account a second time must find the first:
a second account, a second grant of credits or a second Google link would make every later run drift.

Use cases:
- a password persona gets a verified account, a signup record, a profile, a password that works, and the signup credits
  once the account is announced
- making it again finds the same account, sets the password again (so it matches the file the audit keeps) and gives
  no second grant
- a staff persona is staff, and its address is marked as made by an operator
- a Google persona gets an account with no password, linked to the stand-in provider and verified by "google", once
- the persona's `sign_in` picks the kind of account
- a filled-in profile skips onboarding and carries the language; a new learner's stays blank but still has a language
"""

import pytest

from accounts.models import ExternalIdentity, SignupRecord, User
from core.audit.accounts import GoogleAccounts, PasswordAccounts, PersonaAccounts, PersonaProfiles
from core.audit.personas import Persona
from credits.ledger import Ledger

pytestmark = pytest.mark.django_db

PASSWORD = "audit-test-password-1"


def persona(**fields) -> Persona:
    return Persona(**{"slug": "weekly", "name": "Wren Weekly", "purpose": "test", **fields})


class TestPasswordAccounts:
    def test_a_persona_gets_a_verified_account_with_a_profile_a_password_and_the_signup_credits(
        self, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            user, created = PasswordAccounts().ensure(persona(), PASSWORD)

        assert created is True and user.email == "audit-weekly@example.test"
        assert user.is_email_verified and user.check_password(PASSWORD) and not user.is_staff
        assert SignupRecord.objects.filter(user=user).count() == 1 and user.profile.pk
        assert Ledger().balance(user) == 30

    def test_making_it_again_finds_the_account_resets_the_password_and_grants_nothing_twice(
        self, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            first, _ = PasswordAccounts().ensure(persona(), PASSWORD)
        with django_capture_on_commit_callbacks(execute=True):
            again, created = PasswordAccounts().ensure(persona(), "a-second-password-2")

        assert created is False and again.pk == first.pk and User.objects.count() == 1
        again.refresh_from_db()
        assert again.check_password("a-second-password-2") and not again.check_password(PASSWORD)
        assert Ledger().balance(again) == 30
        assert SignupRecord.objects.filter(user=again).count() == 1

    def test_a_staff_persona_is_staff_and_marked_as_made_by_an_operator(self):
        user, _ = PasswordAccounts().ensure(persona(slug="staff", staff=True), PASSWORD)

        assert user.is_staff and user.email_verification_source == User.VerificationSource.OPERATOR


class TestGoogleAccounts:
    def test_the_account_has_no_password_and_is_linked_to_the_stand_in_provider_once(
        self, django_capture_on_commit_callbacks
    ):
        google = persona(slug="google", sign_in="google")

        with django_capture_on_commit_callbacks(execute=True):
            user, created = GoogleAccounts().ensure(google, PASSWORD)
        again, created_again = GoogleAccounts().ensure(google, PASSWORD)

        assert created and not created_again and again.pk == user.pk
        assert not user.has_usable_password() and user.email_verification_source == "google"
        assert ExternalIdentity.objects.filter(user=user, provider="fake").count() == 1
        assert Ledger().balance(user) == 30


class TestPersonaAccounts:
    def test_the_personas_sign_in_picks_the_kind(self):
        accounts = PersonaAccounts()

        password_user, _ = accounts.ensure(persona(), PASSWORD)
        google_user, _ = accounts.ensure(persona(slug="google", sign_in="google"), PASSWORD)

        assert password_user.has_usable_password() and not google_user.has_usable_password()


class TestProfiles:
    def test_a_filled_in_profile_skips_onboarding_and_carries_the_language(self):
        user, _ = PasswordAccounts().ensure(persona(language="hi"), PASSWORD)

        PersonaProfiles().apply(user, persona(language="hi"))

        user.profile.refresh_from_db()
        assert user.profile.preferred_language == "hi" and user.profile.is_complete

    def test_a_new_learners_profile_stays_blank_but_has_a_language(self):
        user, _ = PasswordAccounts().ensure(persona(slug="new-learner", onboarded=False), PASSWORD)

        PersonaProfiles().apply(user, persona(slug="new-learner", onboarded=False))

        user.profile.refresh_from_db()
        assert not user.profile.is_complete and user.profile.preferred_language == "en"
