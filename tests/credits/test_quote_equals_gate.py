"""Unit under test: that the quote a learner is shown and the credits the gate holds are the same number, for every
row of
the pricing matrix (plan §5.4) and every journey (§5.5), because they run the same code.

Why: a screen that promised 3 credits and a gate that took 4 would be the worst bug this feature can have. The quote
endpoint and the gate are built to call one `PriceQuoter`; this checks that they still do, row by row, through the real
endpoint and the real gate, so a change to either that stops sharing the rule fails here.

Use cases:
- for every matrix row, `POST /api/credits/quote` answers the row's credits and its lines, and the gate holds exactly
  that
  many credits with the same lines
- for every journey, the endpoint answers the due-now amount, what follows later, and the total
- a gate and a quote asked at different prices (after an edit) agree with each other at each moment
"""

import uuid

import pytest
from support.pricing_matrix import JOURNEYS, MATRIX

from credits.gate import CreditGate
from credits.models import CreditHold
from credits.pricing.seed import PriceSeed
from lessons.metering import ActionContext, CompletionPoints

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def prices(db):
    PriceSeed().apply()


@pytest.mark.parametrize(("action", "size", "credits", "keys"), MATRIX)
def test_the_quote_and_the_gate_agree_on_every_row(signed_in_client, user, give, ledger, action, size, credits, keys):
    give(user, 100)

    quoted = signed_in_client.post("/api/credits/quote", {"action": str(action), "size": size}, format="json")
    held = CreditGate(ledger=ledger).authorize(
        ActionContext(user, action, size, uuid.uuid4(), f"k-{uuid.uuid4()}", False, CompletionPoints.of(action, size))
    )

    assert quoted.status_code == 200
    body = quoted.json()
    hold = CreditHold.objects.get(pk=held.id)
    assert body["due_now"] == credits == hold.amount == held.meta["credits"]
    assert body["lines"] == hold.lines and [line["key"] for line in body["lines"]] == keys


@pytest.mark.parametrize(("action", "size", "due_now", "later", "total"), JOURNEYS)
def test_the_endpoint_answers_every_journey(signed_in_client, action, size, due_now, later, total):
    response = signed_in_client.post("/api/credits/quote", {"action": str(action), "size": size}, format="json")

    assert response.status_code == 200
    assert (response.json()["due_now"], response.json()["later"], response.json()["total"]) == (due_now, later, total)


def test_after_an_edit_the_quote_and_the_gate_still_agree(signed_in_client, user, give, ledger):
    from datetime import UTC, datetime

    from credits.pricing.book import PriceCatalog
    from lessons.metering import MeteredAction

    give(user, 100)
    size = {"choice": "lesson", "perfect": False}
    action = MeteredAction.LESSON_CONTINUE
    PriceCatalog().revise("lesson.rest", 12, by="staff", now=datetime(2026, 11, 6, tzinfo=UTC))

    quoted = signed_in_client.post("/api/credits/quote", {"action": str(action), "size": size}, format="json")
    held = CreditGate(ledger=ledger).authorize(
        ActionContext(user, action, size, uuid.uuid4(), "k", False, CompletionPoints.of(action, size))
    )

    assert quoted.json()["due_now"] == held.meta["credits"] == 12
