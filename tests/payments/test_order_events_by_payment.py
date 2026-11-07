"""Unit under test: `payments.events.OrderEvents` finding an order by the provider's *payment* reference when the event
names no checkout (credits plan §5.8, D14; phase 10.7).

Why: some providers say a refund or a dispute about the payment, not about the checkout it came from. Stripe's refund
and dispute objects carry a payment intent, never the Checkout Session id the order was stored under. The order has kept
that payment reference since it was paid, so the event must be able to find its order by it, and must not guess when
the reference is one we do not know.

Use cases:
- a refund event with no checkout reference but a known payment reference takes back the credits of that order
- the same event again is a duplicate; the amount of a second, partial one adds up with the first
- a dispute is found the same way
- an event with neither reference, or with a payment reference we do not know, is an unknown order and changes nothing
- the payment reference is looked up inside the event's own gateway (another gateway's identical id is not this order)
- an event that names its checkout still finds the order by that, as before
"""

from datetime import UTC, datetime

import pytest

from credits.ledger import Ledger
from payments.events import OrderEvents
from payments.gateway import PaymentEvent
from payments.models import PaymentEventLog

pytestmark = pytest.mark.django_db
AT = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def event(kind="refunded", *, event_id="refund:re_1", amount=2500, payment_ref="pay_1", provider_ref=""):
    return PaymentEvent(event_id, kind, provider_ref, amount, "INR", AT, payment_ref)


@pytest.fixture
def paid(payments):
    order = payments.buy("one_time", credits=100)
    payments.send("succeeded", order, payment_ref="pay_1")
    return order


class TestFoundByThePaymentReference:
    def test_a_refund_naming_only_the_payment_takes_back_that_orders_credits(self, paid, user):
        applied = OrderEvents().apply("scripted", event(amount=paid.amount_paise // 2))

        paid.refresh_from_db()
        assert applied.outcome == "applied" and applied.order_id == str(paid.pk)
        assert paid.refunded_paise == paid.amount_paise // 2 and Ledger().balance(user) == 50

    def test_the_same_event_again_is_a_duplicate_and_a_second_refund_adds_up(self, paid, user):
        half = paid.amount_paise // 2
        OrderEvents().apply("scripted", event(amount=half))

        again = OrderEvents().apply("scripted", event(amount=half))
        second = OrderEvents().apply("scripted", event(event_id="refund:re_2", amount=half))

        paid.refresh_from_db()
        assert (again.outcome, second.outcome) == ("duplicate", "applied")
        assert paid.refunded_paise == paid.amount_paise and Ledger().balance(user) == 0

    def test_a_dispute_is_found_the_same_way(self, paid, user):
        applied = OrderEvents().apply("scripted", event("disputed", event_id="evt_d", amount=paid.amount_paise))

        assert applied.outcome == "applied" and Ledger().balance(user) == 0


class TestNotGuessing:
    @pytest.mark.parametrize("payment_ref", ["", "pi_nobody_knows"])
    def test_no_reference_or_an_unknown_one_is_an_unknown_order(self, paid, user, payment_ref):
        applied = OrderEvents().apply("scripted", event(payment_ref=payment_ref))

        assert applied.outcome == "unknown_order" and Ledger().balance(user) == 100
        assert PaymentEventLog.objects.get(kind="refunded").order is None

    def test_another_gateways_identical_id_is_not_this_order(self, paid, user):
        applied = OrderEvents().apply("elsewhere", event())

        assert applied.outcome == "unknown_order" and Ledger().balance(user) == 100


class TestStillFoundByTheCheckout:
    def test_an_event_that_names_its_checkout_finds_it_as_before(self, paid, user):
        applied = OrderEvents().apply(
            "scripted", event(amount=paid.amount_paise, payment_ref="", provider_ref=paid.provider_ref)
        )

        assert applied.outcome == "applied" and Ledger().balance(user) == 0
