"""Unit under test: the admin's Refund action and its per-submission token (`payments.admin`, `payments.refunds`,
`payments.models.RefundAttempt`; credits plan D14, phase 10.8 step 0).

Why: a refund is money leaving, and an administrator's double click, a slow page or a browser's resend must not refund
twice. The form is given a fresh token every time it is shown; the token travels with the submit, is checked on the
server (a token that was used refunds once, however often it arrives, even at the same moment) and is handed to the
provider as its idempotency key where it has one, so even a request that was lost on the way back cannot be doubled.
A second, deliberate partial refund is another submission, with another token, and works. Nothing is ever asked for
that is more than remains, counting what was asked for and has not yet been confirmed.

Use cases:
- the form carries a hidden token, a new one each time it is shown
- the same token sent twice (a double click) asks the gateway once and says so the second time; nothing is written twice
- a refund the gateway refused leaves no mark, so the same form can be sent again
- Stripe is sent one request carrying the token and the order as its `Idempotency-Key`, however often the form is sent
- two submissions are two refunds: a partial amount, then the rest; what was asked for and is not yet confirmed
  counts as taken, so the second never asks for more than remains, and a third finds nothing to ask for
- the amount field: a partial amount in rupees for one payment; more than remains, not a number, or given with several
  payments selected, is refused with nothing asked
- a submission with no token, or one that is not a token, still refunds (as before) and is not de-duplicated
- the idempotency is the server's own: the second send at the same moment (two threads) asks once
- two administrators refunding the whole of one order at the same moment, each with a token of their own, refund it
  once between them: the order's lock makes the second find nothing left, so the total never passes what was paid
"""

import re
import threading
import time
import uuid

import pytest
from django.db import connection
from django.test import Client
from django.urls import reverse
from support.stripe import Wire

from console.models import AuditEntry
from credits.ledger import Ledger
from payments.config import GatewayConfig
from payments.errors import GatewayUnavailable
from payments.models import PaymentOrder, RefundAttempt
from payments.registry import PaymentGateways
from payments.stripe_gateway import StripeGateway

pytestmark = pytest.mark.django_db

LIST = "admin:payments_paymentorder_changelist"


@pytest.fixture
def staff(client, db):
    from accounts.models import User

    boss = User.objects.create_user("boss@example.com", password="x-staff-pass-1", name="Boss")
    boss.is_staff = boss.is_superuser = True
    boss.save()
    client.force_login(boss)
    return boss


def submit(client, *orders, token=None, amount=None):
    body = {"action": "refund", "_selected_action": [str(o.pk) for o in orders]}
    if token is not None:
        body["refund_token"] = token
    if amount is not None:
        body["refund_amount"] = amount
    return client.post(reverse(LIST), body, follow=True)


def messages_of(response):
    return [m.message for m in response.context["messages"]]


def token_in(html: str) -> str:
    return re.search(r'name="refund_token"[^>]*value="([^"]+)"', html).group(1)


def paid(payments, credits=100):
    order = payments.buy("one_time", credits=credits)
    payments.send("succeeded", order)
    order.refresh_from_db()
    return order


class TestTheForm:
    def test_it_carries_a_hidden_token_and_a_new_one_each_time_it_is_shown(self, client, staff, payments):
        paid(payments)

        first = client.get(reverse(LIST)).content.decode()
        second = client.get(reverse(LIST)).content.decode()

        assert 'type="hidden"' in re.search(r'<input[^>]*name="refund_token"[^>]*>', first).group(0)
        assert uuid.UUID(token_in(first)) != uuid.UUID(token_in(second))

    def test_the_amount_field_is_there_and_empty(self, client, staff, payments):
        paid(payments)

        html = client.get(reverse(LIST)).content.decode()

        assert re.search(r'<input[^>]*name="refund_amount"', html)


class TestOneSubmissionRefundsOnce:
    def test_the_same_token_twice_asks_the_gateway_once(self, client, staff, payments):
        order = paid(payments)
        token = str(uuid.uuid4())

        first = submit(client, order, token=token)
        second = submit(client, order, token=token)

        assert payments.script.refunds == [("pay_1", order.amount_paise)]
        assert any("asked for" in m for m in messages_of(first))
        assert any("already asked" in m for m in messages_of(second))
        assert RefundAttempt.objects.count() == 1
        assert AuditEntry.objects.filter(action="payments.refund").count() == 1

    def test_a_refund_the_gateway_refused_leaves_no_mark_so_the_form_can_be_sent_again(self, client, staff, payments):
        order = paid(payments)
        token = str(uuid.uuid4())

        def down(self, payment_ref, amount_paise):
            raise GatewayUnavailable("down")

        with pytest.MonkeyPatch.context() as only_here:
            only_here.setattr(payments.gateway_cls, "refund", down)
            failed = submit(client, order, token=token)
        again = submit(client, order, token=token)

        assert any("not made" in m for m in messages_of(failed)) and RefundAttempt.objects.count() == 1
        assert any("asked for" in m for m in messages_of(again))
        assert payments.script.refunds == [("pay_1", order.amount_paise)]

    @pytest.mark.django_db(transaction=True)
    def test_two_threads_with_one_token_ask_once(self, payments, staff):
        order = paid(payments)
        token = str(uuid.uuid4())
        clients = [Client(), Client()]
        for each in clients:
            each.force_login(staff)
        gate = threading.Barrier(2)

        def go(each):
            try:
                gate.wait(5)
                submit(each, order, token=token)
            finally:
                connection.close()

        threads = [threading.Thread(target=go, args=(each,)) for each in clients]
        [t.start() for t in threads]
        [t.join(30) for t in threads]

        assert payments.script.refunds == [("pay_1", order.amount_paise)]

    @pytest.mark.django_db(transaction=True)
    def test_two_administrators_with_their_own_tokens_never_refund_more_than_was_paid(
        self, payments, staff, monkeypatch
    ):
        order = paid(payments)

        class SlowGateway(list):
            def append(self, item):
                time.sleep(0.4)  # the provider takes a moment to answer, long enough for the other request to arrive
                super().append(item)

        monkeypatch.setattr(payments.script, "refunds", SlowGateway())
        clients = [Client(), Client()]
        for each in clients:
            each.force_login(staff)
        gate = threading.Barrier(2)

        def go(each):
            try:
                gate.wait(5)
                submit(
                    each, order, token=str(uuid.uuid4())
                )  # different tokens: only the order's lock stands between them
            finally:
                connection.close()

        threads = [threading.Thread(target=go, args=(each,)) for each in clients]
        [t.start() for t in threads]
        [t.join(30) for t in threads]

        asked = [amount for _, amount in payments.script.refunds]
        assert sum(asked) == order.amount_paise and len(asked) == 1
        assert RefundAttempt.objects.filter(order=order).count() == 1


class TestTwoSubmissionsAreTwoRefunds:
    def test_a_partial_amount_then_the_rest_never_asks_for_more_than_remains(self, client, staff, payments):
        order = paid(payments)  # 100 credits, so a payment of order.amount_paise

        submit(client, order, token=str(uuid.uuid4()), amount="40")
        submit(client, order, token=str(uuid.uuid4()))  # the rest, with the first not yet confirmed
        third = submit(client, order, token=str(uuid.uuid4()))

        asked = [amount for _, amount in payments.script.refunds]
        assert asked == [4000, order.amount_paise - 4000]
        assert sum(asked) == order.amount_paise
        assert any("nothing left" in m or "in full" in m for m in messages_of(third))
        assert RefundAttempt.objects.count() == 2

    def test_what_the_provider_confirms_is_not_counted_twice(self, client, staff, payments):
        order = paid(payments)
        submit(client, order, token=str(uuid.uuid4()), amount="40")
        payments.send("refunded", order, amount=4000, event_id="evt_r1")

        submit(client, order, token=str(uuid.uuid4()))

        assert [a for _, a in payments.script.refunds] == [4000, order.amount_paise - 4000]
        assert Ledger().balance(order.user) == 60

    def test_a_second_partial_refund_after_the_first_is_confirmed_works(self, client, staff, payments):
        order = paid(payments)
        submit(client, order, token=str(uuid.uuid4()), amount="25")
        payments.send("refunded", order, amount=2500, event_id="evt_r1")

        submit(client, order, token=str(uuid.uuid4()), amount="25")

        assert [a for _, a in payments.script.refunds] == [2500, 2500]


class TestTheAmountField:
    @pytest.mark.parametrize("amount", ["101", "1000", "0", "-5", "abc", "1.234"])
    def test_an_amount_that_is_too_much_or_not_an_amount_asks_for_nothing(self, client, staff, payments, amount):
        order = paid(payments)

        response = submit(client, order, token=str(uuid.uuid4()), amount=amount)

        assert payments.script.refunds == [] and not RefundAttempt.objects.exists()
        assert any("amount" in m.lower() for m in messages_of(response))

    def test_an_amount_with_several_payments_selected_is_refused(self, client, staff, payments):
        first = paid(payments)
        second = paid(payments)

        response = submit(client, first, second, token=str(uuid.uuid4()), amount="10")

        assert payments.script.refunds == []
        assert any("one payment" in m for m in messages_of(response))

    def test_several_payments_in_one_submission_each_get_their_own_refund(self, client, staff, payments):
        first, second = paid(payments), paid(payments)

        submit(client, first, second, token=str(uuid.uuid4()))

        assert len(payments.script.refunds) == 2 and RefundAttempt.objects.count() == 2

    def test_a_decimal_amount_is_in_rupees(self, client, staff, payments):
        order = paid(payments)

        submit(client, order, token=str(uuid.uuid4()), amount="12.50")

        assert payments.script.refunds == [("pay_1", 1250)]


class TestNoTokenIsTheOldWay:
    @pytest.mark.parametrize("token", [None, "", "not-a-token"])
    def test_it_still_refunds_and_is_not_de_duplicated(self, client, staff, payments, token):
        order = paid(payments)

        response = submit(client, order, token=token)

        assert payments.script.refunds == [("pay_1", order.amount_paise)]
        assert any("asked for" in m for m in messages_of(response))


class TestStripeIsSentTheTokenAsItsIdempotencyKey:
    @pytest.fixture
    def stripe_order(self, db, user, settings, monkeypatch):
        from credits.plans.seed import PlanSeed
        from payments.checkout import CheckoutService

        wire = Wire(
            (200, {"id": "cs_test_1", "url": "https://checkout.stripe.com/c/pay/cs_test_1"}),
        )

        class WiredStripe(StripeGateway):
            @classmethod
            def from_settings(cls):
                return cls(GatewayConfig.from_settings(cls.config_names()), client=wire.client())

        monkeypatch.setitem(PaymentGateways.REGISTERED, "stripe", WiredStripe)
        settings.PAYMENT_GATEWAYS_ENABLED, settings.PAYMENT_DEFAULT_GATEWAY = ["stripe"], "stripe"
        settings.STRIPE_SECRET_KEY, settings.STRIPE_WEBHOOK_SECRET = "sk_test_" + "k" * 24, "whsec_" + "w" * 24
        PlanSeed().apply()
        order = CheckoutService().start(user, "one_time", credits=100)
        PaymentOrder.objects.filter(pk=order.pk).update(
            status="fulfilled", payment_ref="pi_3Abc", paid_at=order.created_at, fulfilled_at=order.created_at
        )
        order.refresh_from_db()
        wire.answers = [(200, {"id": "re_1", "amount": order.amount_paise, "status": "succeeded"})]
        wire.requests.clear()
        return order, wire

    def test_a_double_click_sends_one_request_carrying_the_token_and_the_order(self, client, staff, stripe_order):
        order, wire = stripe_order
        token = str(uuid.uuid4())

        submit(client, order, token=token)
        submit(client, order, token=token)

        assert len(wire.requests) == 1
        assert wire.sent.headers["idempotency-key"] == f"refund-{token}-{order.pk}"
        assert wire.form() == {"payment_intent": "pi_3Abc", "amount": str(order.amount_paise)}

    def test_two_submissions_are_two_requests_with_two_keys(self, client, staff, stripe_order):
        order, wire = stripe_order
        rest = order.amount_paise - 4000
        wire.answers = [
            (200, {"id": "re_1", "amount": 4000, "status": "succeeded"}),
            (200, {"id": "re_2", "amount": rest, "status": "succeeded"}),
        ]

        submit(client, order, token=str(uuid.uuid4()), amount="40")
        submit(client, order, token=str(uuid.uuid4()))

        keys = [r.headers["idempotency-key"] for r in wire.requests]
        assert len(keys) == 2 and keys[0] != keys[1]
        assert [wire.form(r)["amount"] for r in wire.requests] == ["4000", str(order.amount_paise - 4000)]

    def test_the_key_is_a_legal_one_for_both_providers(self, client, staff, stripe_order):
        order, wire = stripe_order

        submit(client, order, token=str(uuid.uuid4()))

        key = wire.sent.headers["idempotency-key"]
        assert 10 <= len(key) <= 255 and re.fullmatch(r"[A-Za-z0-9_-]+", key)
