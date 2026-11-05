"""Unit under test: `credits.earning.signup.SignupGrant`, the `account_ready` receiver that gives a new account its 30
credits, and the `grant_signup_credits` command that gives them to accounts that existed before (credits plan D10, T30).

Why: every account is promised 30 credits that never expire. Giving them when the account is ready (not when it is made)
is what lets email verification change the sender later without touching the credits code. The grant must happen once
however
often the signal is sent, and the backfill must be safe to run on a live database: twice, with a dry run first, and
never
for an account that is closed.

Use cases:
- registering gives the new learner 30 credits in a bucket that never expires, in one ledger row keyed by the learner
- the grant is repeatable: the signal sent again, or the grant asked for twice, changes nothing
- the amount comes from the settings
- a registration that fails, and a sign-in, give nothing
- a receiver that fails does not undo the registration, and the backfill gives it back later
- the backfill gives the credits to every active account without a grant, once; a second run gives nothing; accounts
  that
  already have it are untouched; closed accounts are skipped
- the dry run reports what it would do and writes nothing, not even a wallet
- the command prints the numbers, and says so when there is nothing to do
"""

from io import StringIO

import pytest
from django.core.management import call_command

from accounts.models import User
from accounts.signals import account_ready
from credits.earning.signup import SignupGrant
from credits.models import CreditBucket, CreditSettings, CreditTransaction, Wallet

pytestmark = pytest.mark.django_db

NEW = {"email": "new@example.com", "password": "correct-horse-battery-staple", "name": "New", "accept_terms": True}


def register(api_client, **extra):
    return api_client.post("/api/auth/register", {**NEW, **extra}, format="json")


def signup_rows(user):
    return CreditTransaction.objects.filter(user=user, idempotency_key=f"signup:{user.pk}")


class TestOnAccountReady:
    def test_registering_gives_30_credits_that_never_expire(self, api_client):
        assert register(api_client).status_code == 201

        user = User.objects.get(email="new@example.com")
        bucket = CreditBucket.objects.get(user=user)
        assert (bucket.source, bucket.amount_granted, bucket.amount_remaining, bucket.expires_at) == (
            "signup",
            30,
            30,
            None,
        )
        row = signup_rows(user).get()
        assert (row.type, row.amount, row.balance_after) == ("grant", 30, 30)

    def test_the_signal_sent_again_changes_nothing(self, api_client):
        register(api_client)
        user = User.objects.get(email="new@example.com")

        account_ready.send(sender=User, user=user)
        account_ready.send(sender=User, user=user)

        assert signup_rows(user).count() == 1 and CreditBucket.objects.filter(user=user).count() == 1

    def test_asking_for_the_grant_twice_gives_it_once(self, user):
        first = SignupGrant().on_account_ready(user)
        again = SignupGrant().on_account_ready(user)

        assert first.created and not again.created and CreditBucket.objects.filter(user=user).count() == 1

    def test_the_amount_comes_from_the_settings(self, api_client):
        CreditSettings.objects.update_or_create(pk=1, defaults={"signup_credits": 45})

        register(api_client)

        assert CreditBucket.objects.get(user__email="new@example.com").amount_granted == 45

    def test_a_refused_registration_and_a_sign_in_give_nothing(self, api_client, user):
        assert register(api_client, accept_terms=False).status_code == 400
        api_client.post(
            "/api/auth/login", {"email": user.email, "password": "correct-horse-battery-staple"}, format="json"
        )

        assert not CreditBucket.objects.exists()

    def test_a_grant_that_fails_does_not_undo_the_registration_and_the_backfill_gives_it_later(
        self, api_client, monkeypatch
    ):
        def broken(self, user):
            raise RuntimeError("the ledger is down")

        monkeypatch.setattr(SignupGrant, "on_account_ready", broken)
        assert register(api_client).status_code == 201
        monkeypatch.undo()
        user = User.objects.get(email="new@example.com")
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
