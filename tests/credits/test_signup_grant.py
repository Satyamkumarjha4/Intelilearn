"""Unit under test: `credits.earning.signup.SignupGrant`, the `account_ready` receiver that gives a new account its 30
credits, and the `grant_signup_credits` command that gives them to accounts that existed before (credits plan D10, T30).

Why: every account is promised 30 credits that never expire. Giving them when the account is ready (not when it is made)
is what lets email verification change the sender later without touching the credits code. The grant must happen once
however
often the signal is sent, and the backfill must be safe to run on a live database: twice, with a dry run first, and
never
for an account that is closed.

Use cases:
- no credits until the code is entered, and exactly 30 after, in a bucket that never expires, in one ledger row keyed by
  the learner
- the grant is repeatable: the signal sent again, or the grant asked for twice, changes nothing
- the amount comes from the settings
- a registration that fails, and a sign-in, give nothing
- a receiver that fails does not undo the account, and the backfill gives it back later
- the backfill gives the credits to every active, verified account without a grant, once; a second run gives nothing;
  accounts that already have it are untouched; closed accounts are skipped; unverified ones are skipped and counted
- an account that proves its email later (a code at sign-in) gets the credits then
- the dry run reports what it would do and writes nothing, not even a wallet
- the command prints the numbers, says so when there is nothing to do, and warns about the unverified it skipped
"""

from io import StringIO

import pytest
from django.core.management import call_command

from accounts.models import User
from accounts.signals import account_ready
from credits.earning.signup import SignupGrant
from credits.models import CreditBucket, CreditSettings, CreditTransaction, Wallet

pytestmark = pytest.mark.django_db

NEW_EMAIL = "new@example.com"


def signup_rows(user):
    return CreditTransaction.objects.filter(user=user, idempotency_key=f"signup:{user.pk}")


class TestOnAccountReady:
    def test_no_credits_until_the_code_is_entered_and_exactly_30_after(self, signup):
        assert signup.register(email=NEW_EMAIL).status_code == 202

        assert not User.objects.filter(email=NEW_EMAIL).exists()  # a pending sign-up is not an account
        assert not CreditBucket.objects.exists() and not CreditTransaction.objects.exists()
        assert signup.verify(NEW_EMAIL, "000000").status_code == 400  # a wrong code gives nothing either
        assert not CreditBucket.objects.exists()

        assert signup.verify(NEW_EMAIL).status_code == 200

        user = User.objects.get(email=NEW_EMAIL)
        bucket = CreditBucket.objects.get(user=user)
        assert (bucket.source, bucket.amount_granted, bucket.amount_remaining, bucket.expires_at) == (
            "signup",
            30,
            30,
            None,
        )
        row = signup_rows(user).get()
        assert (row.type, row.amount, row.balance_after) == ("grant", 30, 30)
        assert CreditTransaction.objects.count() == 1

    def test_the_signal_sent_again_changes_nothing(self, signup):
        signup.complete(email=NEW_EMAIL)
        user = User.objects.get(email=NEW_EMAIL)

        account_ready.send(sender=User, user=user)
        account_ready.send(sender=User, user=user)

        assert signup_rows(user).count() == 1 and CreditBucket.objects.filter(user=user).count() == 1

    def test_asking_for_the_grant_twice_gives_it_once(self, user):
        first = SignupGrant().on_account_ready(user)
        again = SignupGrant().on_account_ready(user)

        assert first.created and not again.created and CreditBucket.objects.filter(user=user).count() == 1

    def test_the_amount_comes_from_the_settings(self, signup):
        CreditSettings.objects.update_or_create(pk=1, defaults={"signup_credits": 45})

        signup.complete(email=NEW_EMAIL)

        assert CreditBucket.objects.get(user__email=NEW_EMAIL).amount_granted == 45

    def test_a_refused_registration_and_a_sign_in_give_nothing(self, signup, api_client, user):
        assert signup.register(email=NEW_EMAIL, accept_terms=False).status_code == 400
        api_client.post(
            "/api/auth/login", {"email": user.email, "password": "correct-horse-battery-staple"}, format="json"
        )

        assert not CreditBucket.objects.exists()

    def test_a_grant_that_fails_does_not_undo_the_account_and_the_backfill_gives_it_later(self, signup, monkeypatch):
        def broken(self, user):
            raise RuntimeError("the ledger is down")

        monkeypatch.setattr(SignupGrant, "on_account_ready", broken)
        assert signup.complete(email=NEW_EMAIL).status_code == 200  # the person has their account
        monkeypatch.undo()
        user = User.objects.get(email=NEW_EMAIL)
        assert not signup_rows(user).exists()

        report = SignupGrant().backfill()

        assert report.granted == 1 and signup_rows(user).count() == 1


class TestTheBackfill:
    def test_it_gives_every_active_account_without_a_grant_the_credits_once(self, user, other_user):
        report = SignupGrant().backfill()

        assert (report.granted, report.already, report.skipped) == (2, 0, 0)
        for learner in (user, other_user):
            assert CreditBucket.objects.get(user=learner).amount_granted == 30

    def test_a_second_run_gives_nothing(self, user, other_user):
        SignupGrant().backfill()

        again = SignupGrant().backfill()

        assert (again.granted, again.already) == (0, 2) and CreditTransaction.objects.count() == 2

    def test_an_account_that_already_has_it_is_untouched(self, user, other_user):
        SignupGrant().on_account_ready(user)

        report = SignupGrant().backfill()

        assert (report.granted, report.already) == (1, 1)
        assert CreditBucket.objects.filter(user=user).count() == 1

    def test_a_closed_account_is_skipped(self, user, other_user):
        User.objects.filter(pk=other_user.pk).update(is_active=False)

        report = SignupGrant().backfill()

        assert (report.granted, report.skipped) == (1, 1)
        assert not CreditBucket.objects.filter(user=other_user).exists()

    def test_the_dry_run_reports_and_writes_nothing(self, user, other_user):
        report = SignupGrant().backfill(dry_run=True)

        assert (report.granted, report.dry_run) == (2, True)
        assert (
            not Wallet.objects.exists() and not CreditBucket.objects.exists() and not CreditTransaction.objects.exists()
        )

    def test_an_unverified_account_gets_nothing_and_is_reported(self, user):
        stranger = User.objects.create_user("unproved@example.com", password="x" * 12, name="Unproved")  # not verified

        report = SignupGrant().backfill()

        assert (report.granted, report.unverified) == (1, 1)
        assert not CreditBucket.objects.filter(user=stranger).exists()
        assert SignupGrant().backfill(dry_run=True).unverified == 1

    def test_an_account_that_proves_its_email_later_gets_the_credits_then(self, signup):
        stranger = User.objects.create_user("unproved@example.com", password="x" * 12, name="Unproved")
        SignupGrant().backfill()
        assert not CreditBucket.objects.filter(user=stranger).exists()

        # signing in with the right password asks for a code; entering it verifies the account and announces it
        assert signup.login(stranger.email, "x" * 12).status_code == 403
        assert signup.verify(stranger.email, purpose="login").status_code == 200

        assert CreditBucket.objects.get(user=stranger).amount_granted == 30

    def test_staff_get_the_credits_too(self, user):
        User.objects.filter(pk=user.pk).update(is_staff=True)

        assert SignupGrant().backfill().granted == 1


class TestTheCommand:
    def run(self, *args):
        out = StringIO()
        call_command("grant_signup_credits", *args, stdout=out)
        return out.getvalue()

    def test_it_says_what_it_did(self, user, other_user):
        assert "Gave the signup credits to 2 accounts" in self.run()

    def test_a_dry_run_says_what_it_would_do_and_does_nothing(self, user):
        out = self.run("--dry-run")

        assert "Dry run" in out and "would give the signup credits to 1 account" in out
        assert not CreditBucket.objects.exists()

    def test_it_says_so_when_there_is_nothing_to_do(self, user):
        self.run()

        assert "Nothing to do" in self.run()

    def test_it_warns_about_the_unverified_accounts_it_skipped(self, user):
        User.objects.create_user("unproved@example.com", password="x" * 12, name="Unproved")

        out = self.run()

        assert "1 unverified skipped" in out
        assert "1 active accounts were skipped because their email was never verified" in out
