"""Unit under test: `POST /api/payments/webhooks/{gateway}` (credits plan T23, §8.2, §11).

Why: it is the one door that anyone on the internet can knock on, and what comes through it makes credits. So it must
prove who is calling before it reads or writes anything, refuse a body that is too big, ignore everything about the
caller (no sign-in, no cookie), and answer the provider in the way that stops it retrying forever. Nothing may reach the
database until the signature is proved.

Use cases:
- a correctly signed success grants the credits and answers 200; the same call again answers 200 and grants nothing more
- a bad, missing or foreign signature is a 400 and does not touch the database, not even one query
- a body that is signed but cannot be read is a 400
- a gateway that does not exist, or is not switched on, is a 404
- a body over 256 KB is a 413, by its declared size and by its real size
- it needs no sign-in and no CSRF cookie, and it is rate limited per address
- a signed event for an order we do not know is answered 200 (the provider must not retry it forever) and is only
  recorded
- an event with an amount that does not match is answered 200 and grants nothing
- the answer carries nothing about the learner or the order
"""

import pytest
from django.test import Client
from rest_framework.throttling import SimpleRateThrottle

from credits.ledger import Ledger
from payments.models import PaymentEventLog, PaymentOrder

pytestmark = pytest.mark.django_db

URL = "/api/payments/webhooks/scripted"


@pytest.fixture
def browserless():
    """A client that insists on the CSRF check, as a browser does, and has no cookies at all."""
    return Client(enforce_csrf_checks=True)


class TestASignedCallback:
    def test_a_success_grants_and_a_repeat_grants_nothing_more(self, payments, user, browserless):
        order = payments.buy("one_time", credits=100)

        first = payments.post(browserless, "succeeded", order, event_id="evt_1")
        again = payments.post(browserless, "succeeded", order, event_id="evt_1")

        assert (first.status_code, again.status_code) == (200, 200) and first.json() == {"received": 1}
        assert Ledger().balance(user) == 100 and PaymentEventLog.objects.count() == 1

    def test_it_needs_no_sign_in_and_no_csrf_cookie(self, payments, api_client):
        order = payments.buy()

        assert payments.post(api_client, "failed", order).status_code == 200

    def test_an_event_for_an_unknown_order_is_answered_ok_and_only_recorded(self, payments, browserless, user):
        order = payments.buy()
        order.provider_ref = "ref_nobody"

        response = payments.post(browserless, "succeeded", order)

        assert response.status_code == 200 and PaymentEventLog.objects.get().outcome == "unknown_order"

    def test_a_wrong_amount_is_answered_ok_and_grants_nothing(self, payments, browserless, user):
        order = payments.buy("one_time", credits=100)

        response = payments.post(browserless, "succeeded", order, amount=1)

        assert response.status_code == 200 and Ledger().balance(user) == 0
        assert PaymentOrder.objects.get().status == "pending"


class TestAnUnprovedCallback:
    def test_a_bad_signature_is_a_400_and_no_query_is_made(self, payments, browserless, django_assert_num_queries):
        order = payments.buy()

        with django_assert_num_queries(0):
            response = payments.post(browserless, "succeeded", order, signed=False)

        assert (response.status_code, response.json()["code"]) == (400, "invalid_webhook")

    def test_a_missing_signature_is_a_400(self, payments, browserless):
        order = payments.buy()

        response = browserless.generic("POST", URL, payments.body("succeeded", order), content_type="application/json")

        assert response.status_code == 400

    def test_a_body_signed_with_another_secret_is_a_400_and_changes_nothing(self, payments, browserless, user):
        order = payments.buy("one_time", credits=100)
        body = payments.body("succeeded", order)

        response = browserless.generic(
            "POST",
            URL,
            body,
            content_type="application/json",
            **{"HTTP_X_SCRIPTED_SIGNATURE": payments.headers(body, "other")["X-Scripted-Signature"]},
        )

        assert response.status_code == 400 and Ledger().balance(user) == 0 and not PaymentEventLog.objects.exists()

    def test_a_signed_body_that_cannot_be_read_is_a_400(self, payments, browserless):
        body = b"not json at all"

        response = browserless.generic(
            "POST",
            URL,
            body,
            content_type="application/json",
            HTTP_X_SCRIPTED_SIGNATURE=payments.headers(body)["X-Scripted-Signature"],
        )

        assert response.status_code == 400

    def test_a_gateway_that_does_not_exist_is_a_404(self, payments, browserless):
        assert (
            browserless.generic(
                "POST", "/api/payments/webhooks/nothing", b"{}", content_type="application/json"
            ).status_code
            == 404
        )

    def test_a_gateway_that_is_not_switched_on_is_a_404(self, payments, browserless, settings):
        settings.PAYMENT_GATEWAYS_ENABLED = []

        assert browserless.generic("POST", URL, b"{}", content_type="application/json").status_code == 404

    def test_a_big_body_is_a_413_by_its_declared_size(self, payments, browserless):
        response = browserless.generic(
            "POST", URL, b"{}", content_type="application/json", CONTENT_LENGTH=str(256 * 1024 + 1)
        )

        assert (response.status_code, response.json()["code"]) == (413, "body_too_large")

    def test_a_big_body_is_a_413_by_its_real_size(self, payments, browserless):
        response = browserless.generic("POST", URL, b"x" * (256 * 1024 + 1), content_type="application/json")

        assert response.status_code == 413

    def test_a_body_just_inside_the_cap_is_read(self, payments, browserless):
        body = b"x" * (256 * 1024)

        response = browserless.generic("POST", URL, body, content_type="application/json")

        assert response.status_code == 400  # read, and not proved


class TestTheDoor:
    def test_it_is_rate_limited_per_address(self, payments, browserless, monkeypatch):
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "payment_webhook", "2/min")

        statuses = [
            browserless.generic("POST", URL, b"{}", content_type="application/json").status_code for _ in range(3)
        ]

        assert statuses == [400, 400, 429]

    def test_the_answer_says_nothing_about_the_order(self, payments, browserless, user):
        order = payments.buy()

        body = payments.post(browserless, "succeeded", order).json()

        assert set(body) == {"received"}
