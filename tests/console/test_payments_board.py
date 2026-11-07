"""Unit under test: `/api/console/payments` and its writes (`console.services.payments.PaymentsBoard`, with
`payments.refunds.RefundDesk` behind the actions; credits plan §10, D14): the payments board.

Why: support has to answer "did this payment go through, and was it refunded?" and has to be able to refund one, safely.
The board shows each order with its state, gateway, amount, what was refunded and every refund asked for with its
state; apart, what a refund could not take back because the credits were already spent. The refund is the same one the
Django admin makes (a token makes a form refund once; never more than remains), and a refund whose provider cannot be
asked can be marked failed by a person, written to the change log.

Use cases:
- orders newest first with state, gateway, amount, refunded, refunds with their state and shortfall; filters by state,
  gateway and a search of the learner or a provider reference; paged; the summary counts shortfalls and waiting refunds
- the shortfalls list: refund and dispute events whose credits were already spent, newest first, with the learner
- refunding asks the gateway for what remains (or the rupees typed), once for a token, never more than remains, with
  the credits coming back only when the provider's event arrives; every refusal is a 409 with its code and words and
  asks nothing; a bad amount is a 400; an unknown order is a 404; the change log has the entry
- marking a refund failed works for a gateway that cannot be asked, frees the amount to ask again, writes the change
  log; it is a 409 `not_markable` for one that is not waiting or that the provider can be asked about; unknown is 404
- reading changes nothing
"""

import uuid

import pytest

from console.models import AuditEntry
from credits.ledger import Ledger
from payments.models import PaymentEventLog, PaymentOrder, RefundAttempt
from payments.registry import PaymentGateways

pytestmark = pytest.mark.django_db

URL = "/api/console/payments"


def paid(payments, credits=100):
    order = payments.buy("one_time", credits=credits)
    payments.send("succeeded", order)
    order.refresh_from_db()
    return order


def refund(client, order, amount=None, token=None):
    body = {"token": str(token or uuid.uuid4())}
    if amount is not None:
        body["amount"] = amount
    return client.post(f"{URL}/{order.pk}/refund", body, format="json")


class TestTheBoard:
    def test_orders_come_newest_first_with_what_support_needs(self, staff_client, payments, user):
        first = paid(payments)
        second = payments.buy("one_time", credits=50)
        RefundAttempt.objects.create(
            token=uuid.uuid4(), order=first, amount_paise=2500, refund_ref="refund_1", state="pending",
            created_at=first.created_at,
        )  # fmt: skip

        page = staff_client.get(URL).json()

        rows = page["results"]
        assert [r["id"] for r in rows] == [str(second.pk), str(first.pk)]
        top = rows[1]
        assert (top["status"], top["gateway"], top["amount_paise"], top["plan"]) == (
            "fulfilled", "scripted", first.amount_paise, "One-time credits",
        )  # fmt: skip
        assert top["learner"]["email"] == user.email
        assert top["refunds"] == [
            {
                "id": top["refunds"][0]["id"], "amount_paise": 2500, "refund_ref": "refund_1", "state": "pending",
                "created_at": top["refunds"][0]["created_at"], "resolved_at": None, "can_mark_failed": True,
            }
        ]  # fmt: skip
        assert page["summary"]["refunds_waiting"] == 1 and page["summary"]["orders_waiting"] == 1

    def test_the_filters(self, staff_client, payments, other_user):
        mine = paid(payments)
        theirs = payments.buy("one_time", credits=50, user=other_user)

        def ids(query):
            return {r["id"] for r in staff_client.get(f"{URL}?{query}").json()["results"]}

        assert ids("status=fulfilled") == {str(mine.pk)}
        assert ids("status=pending") == {str(theirs.pk)}
        assert ids("gateway=scripted") == {str(mine.pk), str(theirs.pk)} and ids("gateway=stripe") == set()
        assert ids("q=grace") == {str(theirs.pk)} and ids(f"q={mine.provider_ref}") == {str(mine.pk)}

    def test_it_is_paged(self, staff_client, payments):
        for credits in range(10, 16):
            paid(payments, credits)

        page = staff_client.get(f"{URL}?page_size=4").json()

        assert len(page["results"]) == 4 and page["next"]
        assert len(staff_client.get(page["next"]).json()["results"]) == 2

    def test_a_shortfall_is_counted_and_listed_with_the_learner(self, staff_client, payments, user):
        order = paid(payments)
        PaymentEventLog.objects.filter(order=order).update(shortfall=0)
        PaymentEventLog.objects.create(
            gateway="scripted", event_id="evt_x", kind="refunded", order=order, amount_paise=order.amount_paise,
            outcome="applied", shortfall=70, received_at=order.created_at,
        )  # fmt: skip

        page = staff_client.get(URL).json()
        listed = staff_client.get(f"{URL}/shortfalls").json()

        assert page["summary"]["shortfalls"] == 1 and page["results"][0]["shortfall_credits"] == 70
        assert [(s["shortfall_credits"], s["learner"]["email"], s["kind"]) for s in listed] == [
            (70, user.email, "refunded")
        ]

    def test_reading_changes_nothing(self, staff_client, payments):
        paid(payments)

        staff_client.get(URL)
        staff_client.get(f"{URL}/shortfalls")

        assert not AuditEntry.objects.exists()


class TestRefunding:
    def test_it_asks_the_gateway_for_what_remains_and_the_credits_wait_for_the_event(
        self, staff_client, staff_user, payments, user
    ):
        order = paid(payments)

        response = refund(staff_client, order)

        body = response.json()
        assert response.status_code == 200 and body["kind"] == "asked" and body["amount_paise"] == order.amount_paise
        assert payments.script.refunds == [("pay_1", order.amount_paise)]
        assert body["order"]["refunds"][0]["state"] == "pending" and Ledger().balance(user) == 100
        entry = AuditEntry.objects.get(action="payments.refund")
        assert (entry.actor_email, entry.target_id) == (staff_user.email, str(order.pk))
        payments.send("refunded", order, event_id="evt_refund")
        assert Ledger().balance(user) == 0

    def test_a_token_refunds_once(self, staff_client, payments):
        order = paid(payments)
        token = uuid.uuid4()

        refund(staff_client, order, token=token)
        again = refund(staff_client, order, token=token)

        assert again.status_code == 200 and again.json()["kind"] == "duplicate"
        assert payments.script.refunds == [("pay_1", order.amount_paise)]

    def test_a_partial_amount_in_rupees_then_the_rest_never_asks_for_more_than_remains(self, staff_client, payments):
        order = paid(payments)

        refund(staff_client, order, amount="40")
        refund(staff_client, order)
        third = refund(staff_client, order)

        assert [a for _, a in payments.script.refunds] == [4000, order.amount_paise - 4000]
        assert third.status_code == 409 and third.json()["code"] == "all_asked"

    @pytest.mark.parametrize(
        ("amount", "code"),
        [("1000", "too_much")],
    )
    def test_an_amount_over_what_remains_is_a_409_with_its_words_and_asks_nothing(
        self, staff_client, payments, amount, code
    ):
        order = paid(payments)

        response = refund(staff_client, order, amount=amount)

        body = response.json()
        assert response.status_code == 409 and body["code"] == code and "more than what remains" in body["detail"]
        assert payments.script.refunds == [] and not RefundAttempt.objects.exists()

    def test_an_order_that_was_not_fulfilled_cannot_be_refunded(self, staff_client, payments):
        order = payments.buy("one_time", credits=100)

        response = refund(staff_client, order)

        assert response.status_code == 409 and response.json()["code"] == "not_fulfilled"
        assert payments.script.refunds == []

    def test_an_order_refunded_in_full_says_so(self, staff_client, payments):
        order = paid(payments)
        payments.send("refunded", order)

        response = refund(staff_client, order)

        assert response.status_code == 409 and response.json()["code"] == "in_full"

    def test_a_gateway_that_cannot_refund_says_where_to_do_it(self, staff_client, payments, monkeypatch):
        order = paid(payments)
        monkeypatch.setattr(payments.gateway_cls, "capabilities", frozenset())

        response = refund(staff_client, order)

        assert response.status_code == 409 and response.json()["code"] == "dashboard"
        assert "own dashboard" in response.json()["detail"]

    @pytest.mark.parametrize("amount", ["abc", "-5", "0", "1.234"])
    def test_an_amount_that_is_not_rupees_is_a_400(self, staff_client, payments, amount):
        order = paid(payments)

        response = refund(staff_client, order, amount=amount)

        assert response.status_code == 400 and "amount" in response.json()["fields"]
        assert payments.script.refunds == []

    def test_the_token_is_required_and_an_unknown_order_is_a_404(self, staff_client, payments):
        order = paid(payments)

        assert staff_client.post(f"{URL}/{order.pk}/refund", {}, format="json").status_code == 400
        assert refund(staff_client, PaymentOrder(pk=uuid.uuid4())).status_code == 404


class TestMarkingAFailedRefund:
    @pytest.fixture
    def attempt(self, payments):
        order = paid(payments)
        return RefundAttempt.objects.create(
            token=uuid.uuid4(), order=order, amount_paise=order.amount_paise, refund_ref="refund_1",
            state="pending", created_at=order.created_at,
        )  # fmt: skip

    def test_it_marks_it_failed_frees_the_amount_and_is_logged(self, staff_client, staff_user, attempt):
        response = staff_client.post(f"/api/console/refunds/{attempt.pk}/mark-failed")

        assert response.status_code == 200 and response.json()["state"] == "failed"
        attempt.refresh_from_db()
        assert attempt.state == "failed" and attempt.resolved_at
        entry = AuditEntry.objects.get(action="payments.refund_failed")
        assert (entry.actor_email, entry.target_id) == (staff_user.email, str(attempt.pk))
        assert refund(staff_client, attempt.order).json()["kind"] == "asked"

    def test_a_refund_that_is_not_waiting_is_a_409(self, staff_client, attempt):
        RefundAttempt.objects.filter(pk=attempt.pk).update(state="confirmed")

        response = staff_client.post(f"/api/console/refunds/{attempt.pk}/mark-failed")

        assert response.status_code == 409 and response.json()["code"] == "not_markable"

    def test_a_refund_the_provider_can_be_asked_about_is_a_409_and_stays_waiting(
        self, staff_client, attempt, monkeypatch
    ):
        monkeypatch.setitem(PaymentGateways.REGISTERED, "scripted", type(
            "Asking", (PaymentGateways.REGISTERED["scripted"],), {
                "capabilities": PaymentGateways.REGISTERED["scripted"].capabilities | {"refund_status"},
            },
        ))  # fmt: skip

        response = staff_client.post(f"/api/console/refunds/{attempt.pk}/mark-failed")

        assert response.status_code == 409 and response.json()["code"] == "not_markable"
        attempt.refresh_from_db()
        assert attempt.state == "pending" and not AuditEntry.objects.exists()

    def test_an_unknown_refund_is_a_404(self, staff_client):
        assert staff_client.post("/api/console/refunds/999999/mark-failed").status_code == 404
