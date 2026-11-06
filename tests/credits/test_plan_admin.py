"""Unit under test: the plan screens of the Django admin (`credits.admin`): the plan table, the read-only purchases and
periods, and the **Give a plan…** action on wallets (credits plan §10, phase 10.4).

Why: before payments exist, an operator needs a way to put a plan on a learner's wallet, to test the whole path and
to make
amends. It is money by another name, so it needs a reason, it must show up in the audit trail, it must be marked as a
gift
(free, from an administrator) so it can never be mistaken for a sale, and sending the form twice must give the plan
once.

Use cases:
- the plan table can be read and its prices and credits edited, but plans cannot be added or deleted; purchases and
  periods
  are read-only
- the action first shows a form listing the wallets and the plans that are switched on
- without a reason, or with a quantity or amount the plan does not allow, the form is shown again and nothing is made
- with a reason it makes a purchase marked as an administrator's, free, with the reason and the administrator on it,
  fulfils
  it, and writes an audit entry for each wallet with the plan and the reason
- Weekly Pro can be given for several weeks (they drip) and one-time credits for an amount
- sending the same form twice gives the plan once
- a wallet whose queue is full is refused with a message, the others in the same request are still given the plan
- the ledger still adds up afterwards
"""

from uuid import uuid4

import pytest
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.urls import reverse

from console.models import AuditEntry
from credits.audit import LedgerAudit
from credits.ledger import Ledger
from credits.models import CreditBucket, Plan, PlanPeriod, PlanPurchase, Wallet
from credits.plans.seed import PlanSeed

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def plans(db):
    PlanSeed().apply()


def url(model, name, *args):
    return reverse(f"admin:credits_{model}_{name}", args=args)


@pytest.fixture
def wallet(user):
    Ledger().grant(user, "signup", 1, "welcome")
    return Wallet.objects.get(user=user)


class TestThePlanTable:
    @pytest.mark.parametrize("model", ["plan", "planpurchase", "planperiod"])
    def test_each_changelist_renders(self, admin_client, model):
        assert admin_client.get(url(model, "changelist")).status_code == 200

    def test_a_price_and_the_credits_can_be_edited(self, admin_client):
        plan = Plan.objects.get(key="monthly_pro")
        form = {f: getattr(plan, f) for f in ("name", "credits", "period_days", "price_paise", "max_quantity", "sort")}
        form |= {"active": "on", "price_paise": 20900, "credits": 520}

        response = admin_client.post(url("plan", "change", plan.pk), form)

        assert response.status_code == 302
        plan.refresh_from_db()
        assert (plan.price_paise, plan.credits) == (20900, 520)

    def test_plans_cannot_be_added_or_deleted(self, admin_client):
        plan = Plan.objects.get(key="monthly_pro")

        assert admin_client.get(url("plan", "add")).status_code == 403
        assert admin_client.post(url("plan", "delete", plan.pk), {"post": "yes"}).status_code == 403
        assert Plan.objects.filter(pk=plan.pk).exists()

    def test_the_key_of_a_plan_cannot_be_changed(self, admin_client):
        plan = Plan.objects.get(key="monthly_pro")
        form = {f: getattr(plan, f) for f in ("name", "credits", "period_days", "price_paise", "max_quantity", "sort")}

        admin_client.post(url("plan", "change", plan.pk), form | {"key": "something_else", "active": "on"})

        plan.refresh_from_db()
        assert plan.key == "monthly_pro"

    def test_purchases_and_periods_are_read_only(self, admin_client, wallet):
        from credits.plans.desk import PurchaseDesk
        from credits.plans.fulfilment import PlanFulfilment

        done = PlanFulfilment().fulfil(PurchaseDesk().open(wallet.user, "weekly_pro", quantity=1))

        for model, row in (("planpurchase", done.purchase), ("planperiod", done.periods[0])):
            assert admin_client.get(url(model, "add")).status_code == 403
            assert admin_client.post(url(model, "change", row.pk), {}).status_code == 403
            assert admin_client.post(url(model, "delete", row.pk), {"post": "yes"}).status_code == 403
            assert admin_client.get(url(model, "change", row.pk)).status_code == 200


class TestGiveAPlan:
    def post(self, client, wallets, **data):
        return client.post(
            url("wallet", "changelist"),
            {"action": "give_plan", ACTION_CHECKBOX_NAME: [w.pk for w in wallets], **data},
        )

    def apply(self, client, wallets, plan="monthly_pro", reason="Apology for the outage", token=None, **more):
        return self.post(client, wallets, apply="1", plan=plan, reason=reason, token=token or uuid4(), **more)

    def test_the_first_request_shows_the_form_the_wallets_and_the_plans_that_are_on(self, admin_client, wallet):
        Plan.objects.filter(key="pro_plus").update(active=False)

        response = self.post(admin_client, [wallet])

        assert response.status_code == 200
        page = response.content.decode()
        assert wallet.user.email in page and 'name="reason"' in page
        assert "Monthly Pro" in page and "Weekly Pro" in page and "Pro Plus" not in page

    @pytest.mark.parametrize("reason", ["", "   "])
    def test_without_a_reason_it_shows_the_form_again_and_makes_nothing(self, admin_client, wallet, reason):
        response = self.apply(admin_client, [wallet], reason=reason)

        assert response.status_code == 200 and b"errorlist" in response.content
        assert not PlanPurchase.objects.exists() and not AuditEntry.objects.exists()

    @pytest.mark.parametrize(
        ("plan", "more"),
        [
            ("weekly_pro", {"quantity": 13}),
            ("weekly_pro", {"quantity": 0}),
            ("monthly_pro", {"quantity": 2}),
            ("one_time", {"credits": 5}),
            ("one_time", {}),
            ("monthly_pro", {"credits": 40}),
            ("platinum", {}),
        ],
    )
    def test_an_amount_the_plan_does_not_allow_is_refused_and_nothing_is_made(self, admin_client, wallet, plan, more):
        response = self.apply(admin_client, [wallet], plan=plan, **more)

        assert response.status_code == 200
        assert not PlanPurchase.objects.exists()

    def test_with_a_reason_it_gives_the_plan_marked_free_and_from_an_administrator(self, admin_client, wallet):
        response = self.apply(admin_client, [wallet], plan="monthly_pro", reason="Apology for the outage")

        assert response.status_code == 302
        purchase = PlanPurchase.objects.get()
        assert (purchase.source, purchase.amount_paise, purchase.status, purchase.user_id) == (
            "admin", 0, "fulfilled", wallet.user_id
        )  # fmt: skip
        assert purchase.meta["reason"] == "Apology for the outage" and purchase.meta["by"] == "admin@example.com"
        assert purchase.meta["list_amount_paise"] == 19900
        assert Ledger().balance(wallet.user) == 1 + 500
        assert LedgerAudit().check_all().ok

    def test_it_writes_the_audit_trail(self, admin_client, wallet):
        self.apply(admin_client, [wallet], plan="weekly_pro", reason="Goodwill", quantity=3)

        entry = AuditEntry.objects.get()
        assert (entry.action, entry.target_type, entry.target_id) == ("credits.give_plan", "wallet", str(wallet.pk))
        assert entry.actor_email == "admin@example.com"
        assert entry.after["plan"] == "weekly_pro" and entry.after["quantity"] == 3
        assert entry.after["reason"] == "Goodwill" and entry.after["purchase"] == str(PlanPurchase.objects.get().pk)

    def test_weekly_pro_can_be_given_for_several_weeks_and_they_drip(self, admin_client, wallet):
        self.apply(admin_client, [wallet], plan="weekly_pro", quantity=3)

        assert PlanPeriod.objects.filter(user=wallet.user).count() == 3
        assert Ledger().balance(wallet.user) == 1 + 100
        assert CreditBucket.objects.filter(user=wallet.user, source="subscription").count() == 1

    def test_one_time_credits_can_be_given_for_an_amount(self, admin_client, wallet):
        self.apply(admin_client, [wallet], plan="one_time", credits=80)

        assert Ledger().balance(wallet.user) == 1 + 80
        assert PlanPurchase.objects.get().credits == 80

    def test_sending_the_same_form_twice_gives_the_plan_once(self, admin_client, wallet):
        token = uuid4()

        self.apply(admin_client, [wallet], token=token)
        self.apply(admin_client, [wallet], token=token)

        assert PlanPurchase.objects.count() == 1 and PlanPeriod.objects.count() == 1
        assert AuditEntry.objects.count() == 1
        assert Ledger().balance(wallet.user) == 1 + 500

    def test_a_wallet_with_a_full_queue_is_refused_with_a_message_and_the_others_are_given_the_plan(
        self, admin_client, wallet, other_user
    ):
        from credits.plans.desk import PurchaseDesk
        from credits.plans.fulfilment import PlanFulfilment

        PlanFulfilment().fulfil(PurchaseDesk().open(wallet.user, "weekly_pro", quantity=12))
        Ledger().grant(other_user, "signup", 1, "welcome-other")
        both = list(Wallet.objects.all())

        response = admin_client.post(
            url("wallet", "changelist"),
            {"action": "give_plan", ACTION_CHECKBOX_NAME: [w.pk for w in both], "apply": "1", "plan": "pro_plus",
             "reason": "Both", "token": uuid4()},
            follow=True,
        )  # fmt: skip

        messages = " ".join(str(m) for m in response.context["messages"])
        assert wallet.user.email in messages and "queue" in messages.lower()
        assert PlanPurchase.objects.filter(source="admin").count() == 1
        assert Ledger().balance(other_user) == 1 + 750

    def test_a_learner_who_is_not_staff_cannot_reach_it(self, signed_in_client, wallet):
        assert signed_in_client.post(url("wallet", "changelist"), {"action": "give_plan"}).status_code == 302
