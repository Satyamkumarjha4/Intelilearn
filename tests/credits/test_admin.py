"""Unit under test: `credits.admin`, the credits screens of the Django admin, and the action that gives or takes
credits.

Why: the admin is where an operator looks into a learner's credits and, rarely, moves them by hand. The ledger,
buckets and
holds must be impossible to edit there (money moves only through `Ledger`), the settings must stay a single editable
row,
and the one manual movement must always carry a reason and go through the ledger so the books still balance.

Use cases:
- every credits changelist renders, and a ledger row, a bucket and a hold can each be opened to read
- the ledger, buckets and holds cannot be added, changed or deleted through the admin
- there can be only one credit-settings row, it cannot be deleted, and editing it changes what the next load reads
- a wallet cannot be added or deleted, shows its balance, and its `credits_exempt` flag can be switched
- the "Give or take credits" action first shows a form listing the selected wallets
- without a reason, or with an amount of zero, it shows the form again with the error and moves nothing
- with an amount and a reason it gives credits through the ledger, with the reason and the administrator's email on the
  row, and the books balance; a negative amount takes credits, and one larger than the balance is refused with a message
  and moves nothing
- every credit movement made there is written to the console's change log with the administrator, the reason and the
  balance before and after; a refusal, a repeat and a missing reason write nothing
- sending the same form twice moves the credits once
- a learner who is not staff cannot reach any of it
"""

from uuid import uuid4

import pytest
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.urls import reverse

from credits.audit import LedgerAudit
from credits.models import CreditBucket, CreditHold, CreditSettings, CreditTransaction, Wallet

pytestmark = pytest.mark.django_db

MODELS = ["wallet", "creditbucket", "credithold", "credittransaction", "creditsettings"]


def url(model, name, *args):
    return reverse(f"admin:credits_{model}_{name}", args=args)


@pytest.fixture
def funded(ledger, give, user):
    give(user, 10)
    ledger.place_hold(user, 2, "lesson.create", "h", subject_id=uuid4())
    CreditSettings.load()
    return user


@pytest.mark.parametrize("model", MODELS)
def test_each_changelist_renders(admin_client, funded, model):
    assert admin_client.get(url(model, "changelist")).status_code == 200


def test_a_ledger_row_a_bucket_and_a_hold_can_be_opened_to_read(admin_client, funded):
    for model, obj in [
        ("credittransaction", CreditTransaction.objects.first()),
        ("creditbucket", CreditBucket.objects.first()),
        ("credithold", CreditHold.objects.first()),
    ]:
        assert admin_client.get(url(model, "change", obj.pk)).status_code == 200


@pytest.mark.parametrize("model", ["creditbucket", "credithold", "credittransaction"])
def test_the_ledger_buckets_and_holds_cannot_be_added_changed_or_deleted(admin_client, funded, model):
    row = {"creditbucket": CreditBucket, "credithold": CreditHold, "credittransaction": CreditTransaction}[model]
    obj = row.objects.first()

    assert admin_client.get(url(model, "add")).status_code == 403
    assert admin_client.post(url(model, "change", obj.pk), {}).status_code == 403
    assert admin_client.post(url(model, "delete", obj.pk), {"post": "yes"}).status_code == 403
    assert row.objects.filter(pk=obj.pk).exists()


def test_there_can_be_only_one_settings_row_and_it_cannot_be_deleted(admin_client):
    settings = CreditSettings.load()

    assert admin_client.get(url("creditsettings", "add")).status_code == 403
    assert admin_client.get(url("creditsettings", "delete", settings.pk)).status_code == 403
    assert CreditSettings.objects.count() == 1


def test_editing_the_settings_changes_what_is_read_next(admin_client):
    settings = CreditSettings.load()
    form = {f.name: getattr(settings, f.name) for f in CreditSettings._meta.concrete_fields if f.name != "id"}

    response = admin_client.post(url("creditsettings", "change", settings.pk), {**form, "signup_credits": 45})

    assert response.status_code == 302 and CreditSettings.load().signup_credits == 45


def test_a_settings_form_whose_smallest_purchase_exceeds_the_largest_is_refused(admin_client):
    settings = CreditSettings.load()
    form = {f.name: getattr(settings, f.name) for f in CreditSettings._meta.concrete_fields if f.name != "id"}

    response = admin_client.post(
        url("creditsettings", "change", settings.pk), {**form, "min_one_time_credits": 9000, "max_one_time_credits": 10}
    )

    assert response.status_code == 200 and CreditSettings.load().min_one_time_credits == 10


class TestTheWallet:
    def test_it_cannot_be_added_or_deleted_and_shows_the_balance(self, admin_client, funded):
        wallet = Wallet.objects.get(user=funded)

        assert admin_client.get(url("wallet", "add")).status_code == 403
        assert admin_client.post(url("wallet", "delete", wallet.pk), {"post": "yes"}).status_code == 403
        page = admin_client.get(url("wallet", "change", wallet.pk)).content.decode()
        assert "8" in page  # 10 granted, 2 held

    def test_the_exempt_flag_can_be_switched(self, admin_client, funded):
        wallet = Wallet.objects.get(user=funded)

        response = admin_client.post(url("wallet", "change", wallet.pk), {"credits_exempt": "on"})

        assert response.status_code == 302 and Wallet.objects.get(pk=wallet.pk).credits_exempt is True


class TestGiveOrTakeCredits:
    def post(self, client, wallets, **data):
        body = {"action": "adjust_credits", ACTION_CHECKBOX_NAME: [w.pk for w in wallets], **data}
        return client.post(url("wallet", "changelist"), body)

    def apply(self, client, wallets, amount, reason, token=None, **kwargs):
        return client.post(
            url("wallet", "changelist"),
            {"action": "adjust_credits", ACTION_CHECKBOX_NAME: [w.pk for w in wallets], "apply": "1",
             "amount": amount, "reason": reason, "token": token or uuid4()},
            **kwargs,
        )  # fmt: skip

    def test_the_first_request_shows_the_form_and_the_selected_wallets(self, admin_client, funded):
        wallet = Wallet.objects.get(user=funded)

        response = self.post(admin_client, [wallet])

        assert response.status_code == 200
        page = response.content.decode()
        assert funded.email in page and 'name="reason"' in page and 'name="amount"' in page

    @pytest.mark.parametrize(("amount", "reason"), [(5, ""), (5, "   "), (0, "why"), ("", "why")])
    def test_without_a_reason_or_an_amount_it_shows_the_form_again_and_moves_nothing(
        self, admin_client, funded, amount, reason
    ):
        wallet = Wallet.objects.get(user=funded)
        before = CreditTransaction.objects.count()

        response = self.apply(admin_client, [wallet], amount, reason)

        assert response.status_code == 200 and b"errorlist" in response.content
        assert CreditTransaction.objects.count() == before

    def test_with_a_reason_it_gives_credits_through_the_ledger_and_says_who_and_why(self, admin_client, funded, ledger):
        wallet = Wallet.objects.get(user=funded)

        response = self.apply(admin_client, [wallet], 25, "Goodwill after the outage")

        assert response.status_code == 302
        row = CreditTransaction.objects.filter(type="admin_adjust").get()
        assert (row.amount, row.user_id) == (25, funded.pk)
        assert row.meta == {"reason": "Goodwill after the outage", "actor": "admin@example.com"}
        assert ledger.balance(funded) == 8 + 25 and LedgerAudit().check_all().ok

    def test_a_negative_amount_takes_credits_and_one_beyond_the_balance_is_refused(self, admin_client, funded, ledger):
        wallet = Wallet.objects.get(user=funded)

        self.apply(admin_client, [wallet], -3, "Granted twice")
        assert ledger.balance(funded) == 5

        response = self.apply(admin_client, [wallet], -50, "Too much", follow=True)

        assert ledger.balance(funded) == 5
        assert CreditTransaction.objects.filter(type="admin_adjust").count() == 1
        assert "50 credits are needed and 5 are available" in " ".join(str(m) for m in response.context["messages"])

    def test_sending_the_same_form_twice_moves_the_credits_once(self, admin_client, funded, ledger):
        wallet = Wallet.objects.get(user=funded)
        token = uuid4()

        self.apply(admin_client, [wallet], 10, "Once", token=token)
        self.apply(admin_client, [wallet], 10, "Once", token=token)

        assert CreditTransaction.objects.filter(type="admin_adjust").count() == 1 and ledger.balance(funded) == 18

    def test_it_writes_the_change_log_with_who_why_and_the_balance_before_and_after(self, admin_client, funded):
        from console.models import AuditEntry

        wallet = Wallet.objects.get(user=funded)

        self.apply(admin_client, [wallet], 25, "Goodwill after the outage")

        entry = AuditEntry.objects.get()
        assert (entry.action, entry.target_type, entry.target_id) == ("credits.adjust", "wallet", str(wallet.pk))
        assert entry.actor_email == "admin@example.com"
        assert entry.before == {"balance": 8}
        assert entry.after == {"balance": 33, "amount": 25, "reason": "Goodwill after the outage"}

    def test_a_refusal_a_repeat_and_a_missing_reason_write_nothing_to_the_change_log(self, admin_client, funded):
        from console.models import AuditEntry

        wallet = Wallet.objects.get(user=funded)
        token = uuid4()
        self.apply(admin_client, [wallet], -50, "Too much")  # more than the balance
        self.apply(admin_client, [wallet], 5, "")  # no reason
        assert AuditEntry.objects.count() == 0

        self.apply(admin_client, [wallet], 5, "Once", token=token)
        self.apply(admin_client, [wallet], 5, "Once", token=token)

        assert AuditEntry.objects.count() == 1

    def test_it_works_for_several_wallets_at_once(self, admin_client, funded, other_user, give):
        give(other_user, 1)
        wallets = list(Wallet.objects.all())

        self.apply(admin_client, wallets, 5, "Both")

        assert CreditTransaction.objects.filter(type="admin_adjust").count() == 2


def test_a_learner_who_is_not_staff_cannot_reach_it(signed_in_client, funded):
    assert signed_in_client.get(url("wallet", "changelist")).status_code == 302  # sent to the admin login
