"""Unit under test: the payments admin (credits plan D14, §10).

Why: refunds are made by an administrator, through the provider. The screen must not move money or credits itself: a
gateway that can refund is asked to, a gateway that cannot is named so the administrator does it in the provider's own
dashboard, and in both cases the credits come back only when the provider's refund event arrives. The rows are read-
only.

Use cases:
- orders and their events can be read and not added, changed or deleted
- Refund on a fulfilled order of a gateway that can refund asks it for the unrefunded amount, writes a change-log entry,
  and takes no credits back yet
- Refund on an order whose gateway cannot refund, or that has no payment reference, says where to do it and asks nothing
- Refund on an order that is not fulfilled, or is refunded in full, refuses
- the credits come back when the refund event arrives
"""

import pytest
from django.contrib import admin
from django.urls import reverse

from console.models import AuditEntry
from credits.ledger import Ledger
from payments.models import PaymentEventLog, PaymentOrder

pytestmark = pytest.mark.django_db


@pytest.fixture
def staff(client, db):
    from accounts.models import User

    boss = User.objects.create_user("boss@example.com", password="x-staff-pass-1", name="Boss")
    boss.is_staff = boss.is_superuser = True
    boss.save()
    client.force_login(boss)
    return boss


def refund(client, *orders):
    return client.post(
        reverse("admin:payments_paymentorder_changelist"),
        {"action": "refund", "_selected_action": [str(o.pk) for o in orders]},
        follow=True,
    )


def messages_of(response):
    return [m.message for m in response.context["messages"]]


def paid(payments, credits=100):
    order = payments.buy("one_time", credits=credits)
    payments.send("succeeded", order)
    order.refresh_from_db()
    return order


class TestTheScreens:
    @pytest.mark.parametrize("model", [PaymentOrder, PaymentEventLog])
    def test_they_are_read_only(self, rf, staff, model):
        model_admin = admin.site._registry[model]
        request = rf.get("/")
        request.user = staff

        assert not model_admin.has_add_permission(request)
        assert not model_admin.has_change_permission(request)
        assert not model_admin.has_delete_permission(request)

    def test_the_lists_open(self, client, staff, payments):
        paid(payments)

        for name in ("payments_paymentorder_changelist", "payments_paymenteventlog_changelist"):
            assert client.get(reverse(f"admin:{name}")).status_code == 200


class TestRefund:
    def test_it_asks_the_gateway_for_what_is_left_and_writes_the_change_log(self, client, staff, payments, user):
        order = paid(payments)

        response = refund(client, order)

        assert payments.script.refunds == [("pay_1", order.amount_paise)]
        entry = AuditEntry.objects.get(action="payments.refund")
        assert (entry.actor_email, entry.target_id, entry.after["amount_paise"]) == (
            "boss@example.com",
            str(order.pk),
            order.amount_paise,
        )
        assert any("asked for" in m for m in messages_of(response))
        assert Ledger().balance(user) == 100  # the credits come back when the provider says so, not now

    def test_the_credits_come_back_when_the_refund_event_arrives(self, client, staff, payments, user):
        order = paid(payments)
        refund(client, order)

        payments.send("refunded", order, event_id="evt_refund")

        assert Ledger().balance(user) == 0

    def test_only_what_is_left_is_asked_for_after_a_partial_refund(self, client, staff, payments):
        order = paid(payments)
        payments.send("refunded", order, amount=2500)

        refund(client, order)

        assert payments.script.refunds == [("pay_1", order.amount_paise - 2500)]

    def test_a_gateway_that_cannot_refund_says_where_to_do_it(self, client, staff, payments, monkeypatch):
        order = paid(payments)
        monkeypatch.setattr(payments.gateway_cls, "capabilities", frozenset())

        response = refund(client, order)

        assert payments.script.refunds == [] and not AuditEntry.objects.filter(action="payments.refund").exists()
        assert any("dashboard" in m and "Scripted payments" in m for m in messages_of(response))

    def test_an_order_without_a_payment_reference_says_where_to_do_it(self, client, staff, payments):
        order = paid(payments)
        PaymentOrder.objects.filter(pk=order.pk).update(payment_ref="")

        response = refund(client, order)

        assert payments.script.refunds == [] and any("dashboard" in m for m in messages_of(response))

    def test_an_order_that_was_not_fulfilled_is_refused(self, client, staff, payments):
        order = payments.buy()

        response = refund(client, order)

        assert payments.script.refunds == [] and any(
            "only a payment that was fulfilled" in m for m in messages_of(response)
        )

    def test_an_order_refunded_in_full_is_not_refunded_again(self, client, staff, payments):
        order = paid(payments)
        payments.send("refunded", order)

        response = refund(client, order)

        assert payments.script.refunds == [] and any("in full already" in m for m in messages_of(response))

    def test_a_provider_that_refuses_is_reported_and_nothing_is_logged(self, client, staff, payments, monkeypatch):
        order = paid(payments)
        from payments.errors import GatewayUnavailable

        def refuse(self, payment_ref, amount_paise):
            raise GatewayUnavailable("no")

        monkeypatch.setattr(payments.gateway_cls, "refund", refuse)

        response = refund(client, order)

        assert (
            any("was not made" in m for m in messages_of(response))
            and not AuditEntry.objects.filter(action="payments.refund").exists()
        )
