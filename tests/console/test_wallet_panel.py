"""Unit under test: `/api/console/learners/{id}/wallet` and its writes (`console.services.wallets.WalletPanel`; credits
plan §10, D12): a learner's wallet as support sees it, and the two things support may change.

Why: when a learner says "my credits are wrong", support needs the balance, what it is made of, the last movements and
a way to put it right that leaves a trace. Giving or taking credits without saying why would leave the only record of a
hand-made change blank, so the reason is required; sending the form twice must not move credits twice; being staff
must not exempt anyone from paying.

Use cases:
- the panel shows the balance, what is set aside, the live credits (soonest to run out first), the last 50 ledger rows
  newest first with the reason of a hand-made one, and the exempt switch; another learner's credits are not in it
- an unknown learner is a 404; a learner with no wallet yet reads as an empty one and nothing is created by reading
- giving credits adds a bucket that never expires and a ledger row carrying the reason, and writes the change log with
  the balance before and after and who did it; taking them takes the soonest to expire first and never below zero
- the reason is required (blank, spaces or missing), the amount must be a whole number other than zero, and a refusal
  moves nothing and writes nothing
- the same token twice moves the credits once and writes one entry; a new token is a new movement
- the exempt switch is saved, written to the change log with before and after, and an exempt learner's work costs 0;
  switching it to what it is writes nothing; being staff does not exempt
"""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from console.models import AuditEntry
from credits.exempt import ExemptPolicy
from credits.ledger import Ledger
from credits.models import CreditBucket, CreditTransaction, Wallet

pytestmark = pytest.mark.django_db


def url(user, tail=""):
    return f"/api/console/learners/{user.pk}/wallet{tail}"


def adjust(client, user, amount=None, reason="Goodwill after a failed lesson", token=None, **extra):
    body = {"amount": amount, "reason": reason, "token": str(token or uuid.uuid4()), **extra}
    return client.post(url(user, "/adjust"), {k: v for k, v in body.items() if v is not None}, format="json")


class TestThePanel:
    def test_it_shows_the_balance_the_live_credits_and_the_last_rows(self, staff_client, user, other_user, credits_on):
        soon = credits_on.fund(user, 5, days=2, source="daily")
        credits_on.fund(user, 30, source="signup")
        credits_on.fund(other_user, 99)
        Ledger().adjust(user, 3, "k1", reason="Compensation", actor="x@example.com")

        body = staff_client.get(url(user)).json()

        assert (body["balance"], body["reserved"], body["credits_exempt"]) == (38, 0, False)
        assert body["learner"]["email"] == user.email
        assert [b["source"] for b in body["buckets"]] == ["daily", "signup", "admin_grant"]  # soonest to run out first
        assert body["buckets"][0]["remaining"] == 5 and body["buckets"][0]["lapsed"] is False
        rows = body["transactions"]
        assert (
            rows[0]["type"] == "admin_adjust" and rows[0]["reason"] == "Compensation" and rows[0]["balance_after"] == 38
        )
        assert len(rows) == 3 and soon

    def test_only_the_last_fifty_rows_come_and_newest_first(self, staff_client, user, credits_on):
        for n in range(55):
            Ledger().adjust(user, 1, f"k{n}", reason="r", actor="x@example.com")

        rows = staff_client.get(url(user)).json()["transactions"]

        assert len(rows) == 50 and rows[0]["id"] > rows[-1]["id"]

    def test_a_lapsed_bucket_is_marked_and_not_counted(self, staff_client, user, credits_on):
        credits_on.fund(user, 5, days=1)
        CreditBucket.objects.update(expires_at=timezone.now() - timedelta(hours=1))

        body = staff_client.get(url(user)).json()

        assert body["balance"] == 0 and body["buckets"][0]["lapsed"] is True

    def test_an_unknown_learner_is_a_404(self, staff_client):
        assert staff_client.get(f"/api/console/learners/{uuid.uuid4()}/wallet").status_code == 404

    def test_a_learner_with_no_wallet_reads_empty_and_reading_makes_none(self, staff_client, user):
        body = staff_client.get(url(user)).json()

        assert (body["balance"], body["buckets"], body["transactions"]) == (0, [], [])
        assert not Wallet.objects.filter(pk=user.pk).exists()


class TestGivingAndTaking:
    def test_giving_adds_a_bucket_that_never_expires_with_the_reason_and_is_logged(
        self, staff_client, staff_user, user
    ):
        response = adjust(staff_client, user, 25)

        body = response.json()
        assert response.status_code == 200 and body["balance"] == 25
        bucket = CreditBucket.objects.get(user=user)
        assert (bucket.source, bucket.expires_at) == ("admin_grant", None)
        row = CreditTransaction.objects.get(user=user)
        assert row.meta["reason"] == "Goodwill after a failed lesson" and row.meta["actor"] == staff_user.email
        entry = AuditEntry.objects.get(action="credits.adjust")
        assert (entry.actor_email, entry.target_id) == (staff_user.email, str(user.pk))
        assert (entry.before["balance"], entry.after["balance"], entry.after["reason"]) == (
            0, 25, "Goodwill after a failed lesson",
        )  # fmt: skip

    def test_taking_takes_the_soonest_to_expire_first_and_never_below_zero(self, staff_client, user, credits_on):
        credits_on.fund(user, 10, days=1, source="daily")
        credits_on.fund(user, 10, source="signup")

        adjust(staff_client, user, -4)
        refused = adjust(staff_client, user, -100)

        assert refused.status_code == 400 and "amount" in refused.json()["fields"]
        assert Ledger().balance(user) == 16
        assert CreditBucket.objects.get(source="daily").amount_remaining == 6

    @pytest.mark.parametrize("reason", ["", "   ", None])
    def test_the_reason_is_required_and_a_refusal_moves_and_writes_nothing(self, staff_client, user, reason):
        response = adjust(staff_client, user, 10, reason=reason)

        assert response.status_code == 400 and "reason" in response.json()["fields"]
        assert not CreditTransaction.objects.exists() and not AuditEntry.objects.exists()

    @pytest.mark.parametrize("amount", [0, 1.5, "ten", None])
    def test_the_amount_must_be_a_whole_number_other_than_zero(self, staff_client, user, amount):
        response = adjust(staff_client, user, amount)

        assert response.status_code == 400 and "amount" in response.json()["fields"]
        assert not CreditTransaction.objects.exists()

    def test_the_same_token_twice_moves_the_credits_once_and_writes_one_entry(self, staff_client, user):
        token = uuid.uuid4()

        adjust(staff_client, user, 10, token=token)
        again = adjust(staff_client, user, 10, token=token)

        assert again.status_code == 200 and Ledger().balance(user) == 10
        assert AuditEntry.objects.filter(action="credits.adjust").count() == 1

    def test_a_new_token_is_a_new_movement(self, staff_client, user):
        adjust(staff_client, user, 10)
        adjust(staff_client, user, 10)

        assert Ledger().balance(user) == 20

    def test_an_unknown_learner_is_a_404_and_moves_nothing(self, staff_client):
        response = staff_client.post(
            f"/api/console/learners/{uuid.uuid4()}/wallet/adjust", {"amount": 5, "reason": "x"}, format="json"
        )

        assert response.status_code == 404 and not CreditTransaction.objects.exists()


class TestTheExemptSwitch:
    def test_it_is_saved_logged_with_before_and_after_and_makes_work_free(self, staff_client, staff_user, user):
        response = staff_client.patch(url(user), {"credits_exempt": True}, format="json")

        assert response.status_code == 200 and response.json()["credits_exempt"] is True
        assert ExemptPolicy().applies_to(user)
        entry = AuditEntry.objects.get(action="credits.exempt")
        assert (entry.actor_email, entry.before, entry.after) == (
            staff_user.email, {"credits_exempt": False}, {"credits_exempt": True},
        )  # fmt: skip

    def test_switching_it_back_works_and_the_same_value_writes_nothing(self, staff_client, user):
        staff_client.patch(url(user), {"credits_exempt": True}, format="json")
        staff_client.patch(url(user), {"credits_exempt": True}, format="json")
        staff_client.patch(url(user), {"credits_exempt": False}, format="json")

        assert not ExemptPolicy().applies_to(user)
        assert AuditEntry.objects.filter(action="credits.exempt").count() == 2

    def test_a_value_that_is_not_a_switch_is_refused(self, staff_client, user):
        assert staff_client.patch(url(user), {"credits_exempt": "maybe"}, format="json").status_code == 400
        assert staff_client.patch(url(user), {}, format="json").status_code == 400

    def test_being_staff_does_not_exempt_anyone(self, staff_user):
        assert not ExemptPolicy().applies_to(staff_user)
