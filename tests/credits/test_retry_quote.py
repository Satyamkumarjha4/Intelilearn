"""Unit under test: `GET /api/credits/retry-quote?lesson=<id>` and `credits.retry.RetryQuote` (credits plan §9.2).

Why: the Retry card on a failed lesson must say what pressing it will cost, and a Retry asks for the same action again
(the failure gave the credits back). The screen cannot work that out: it does not know what the stopped run was asked
with, so the server reads it from the run and prices it with the same rule the gate uses. A Retry whose work was kept
costs nothing and must say so, not show a price that will not be charged.

Use cases:
- it needs a signed-in learner, a lesson id that is a uuid (400), and a lesson of the learner's own (404, also for
  another learner's lesson)
- a failed run that held credits quotes what the same action costs now, equal to the quote endpoint for its size
- a run whose work succeeded, a lesson whose runs held nothing, and a lesson with no run cost nothing
- a cancelled run (a Stop) is priced like a failed one
- the answer has the shape of a quote and says whether the learner is exempt
"""

import uuid

import pytest

from credits.models import Wallet
from credits.pricing.seed import PriceSeed
from lessons.metering import Authorization, CompletionPoints, MeteredAction
from lessons.models import GraphRun

pytestmark = pytest.mark.django_db

URL = "/api/credits/retry-quote"
SIZE = {"entry": "diagnostic", "intent": "lesson", "origin": "direct", "covers": "diagnostic"}


@pytest.fixture(autouse=True)
def prices(db):
    PriceSeed().apply()


def authorization(action=MeteredAction.LESSON_CREATE, size=None):
    size = SIZE if size is None else size
    return Authorization(
        id=str(uuid.uuid4()), action=action, size=size, resume=False, completes_at=CompletionPoints.of(action, size)
    )


def run(lesson, held=None, settled=None, status=GraphRun.Status.FAILED):
    payload = {"authorization": {**held.to_payload(), "settled": settled}} if held else {}
    return GraphRun.objects.create(lesson=lesson, graph=GraphRun.Graph.FLOW, status=status, payload=payload)


def quote_of(client, action="lesson.create", size=None):
    return client.post(
        "/api/credits/quote", {"action": action, "size": SIZE if size is None else size}, format="json"
    ).json()


class TestAccess:
    def test_it_needs_a_signed_in_learner(self, api_client):
        assert api_client.get(f"{URL}?lesson={uuid.uuid4()}").status_code == 401

    @pytest.mark.parametrize("query", ["", "?lesson=nope"])
    def test_a_missing_or_malformed_lesson_is_a_400(self, signed_in_client, query):
        assert signed_in_client.get(URL + query).status_code == 400

    def test_a_lesson_that_is_not_there_is_a_404(self, signed_in_client):
        assert signed_in_client.get(f"{URL}?lesson={uuid.uuid4()}").status_code == 404

    def test_another_learners_lesson_is_a_404(self, signed_in_client, other_user, make_lesson):
        lesson = make_lesson(owner=other_user)
        run(lesson, authorization(), settled="failed")

        assert signed_in_client.get(f"{URL}?lesson={lesson.id}").status_code == 404

    def test_a_read_makes_no_wallet(self, signed_in_client, user, make_lesson):
        lesson = make_lesson()
        run(lesson, authorization(), settled="failed")

        signed_in_client.get(f"{URL}?lesson={lesson.id}")

        assert not Wallet.objects.filter(user=user).exists()


class TestThePrice:
    @pytest.mark.parametrize("status", [GraphRun.Status.FAILED, GraphRun.Status.CANCELLED])
    @pytest.mark.parametrize("settled", ["failed", "cancelled", None])
    def test_a_run_that_held_credits_and_did_not_finish_quotes_the_action_again(
        self, signed_in_client, make_lesson, status, settled
    ):
        lesson = make_lesson()
        run(lesson, authorization(), settled=settled, status=status)

        body = signed_in_client.get(f"{URL}?lesson={lesson.id}").json()

        assert body == quote_of(signed_in_client) and body["due_now"] > 0

    def test_it_uses_what_the_stopped_run_was_asked_with(self, signed_in_client, make_lesson):
        size = {
            "entry": "diagnostic",
            "intent": "sheets",
            "origin": "direct",
            "covers": "diagnostic",
            "sheets": 2,
            "grounding": "quiz",
        }
        lesson = make_lesson()
        run(lesson, authorization(size=size), settled="failed")

        assert signed_in_client.get(f"{URL}?lesson={lesson.id}").json() == quote_of(signed_in_client, size=size)

    def test_the_newest_run_is_the_one_that_counts(self, signed_in_client, make_lesson):
        lesson = make_lesson()
        run(lesson, authorization(), settled="failed")
        newer = {"entry": "self_rating", "intent": "lesson", "origin": "direct", "covers": "all"}
        run(lesson, authorization(size=newer), settled="failed")

        body = signed_in_client.get(f"{URL}?lesson={lesson.id}").json()

        assert body == quote_of(signed_in_client, size=newer)


class TestNothingToPay:
    def test_work_that_was_kept_costs_nothing(self, signed_in_client, make_lesson):
        lesson = make_lesson()
        run(lesson, authorization(), settled="succeeded")

        body = signed_in_client.get(f"{URL}?lesson={lesson.id}").json()

        assert (body["due_now"], body["later"], body["total"], body["lines"], body["later_lines"]) == (0, 0, 0, [], [])

    def test_a_run_that_held_nothing_costs_nothing(self, signed_in_client, make_lesson):
        lesson = make_lesson()
        run(lesson, held=None)

        assert signed_in_client.get(f"{URL}?lesson={lesson.id}").json()["total"] == 0

    def test_a_lesson_with_no_run_costs_nothing(self, signed_in_client, make_lesson):
        assert signed_in_client.get(f"{URL}?lesson={make_lesson().id}").json()["total"] == 0

    def test_it_says_whether_the_learner_is_exempt(self, signed_in_client, user, make_lesson):
        from credits.ledger import Ledger

        Ledger().grant(user, "signup", 1, "g")
        Wallet.objects.filter(user=user).update(credits_exempt=True)
        lesson = make_lesson()
        run(lesson, authorization(), settled="failed")

        assert signed_in_client.get(f"{URL}?lesson={lesson.id}").json()["exempt"] is True
