"""Unit under test: `credits.views` (`GET /api/credits/wallet`, `POST /api/credits/quote`, `GET
/api/credits/transactions`)
and `credits.words.TransactionWords`.

Why: these are the first credits a learner can see. The wallet must be right and private (nobody sees another learner's
credits), a read must never create anything, the quote must refuse anything that is not a real question about a real
price (so it cannot be used to probe), and the history must read like a person wrote it: a learner never sees the words
reserve-of-a-hold, ledger, bucket or transaction, and never an internal id they cannot use.

Use cases:
- all three need a signed-in learner (401), and a read makes no wallet
- the wallet gives the balance, what is reserved for work under way, the credits that can be spent in the order they
  will
  be, the next expiry and whether the learner is exempt; lapsed, empty and revoked credits are left out; another
  learner's
  credits are never shown
- the quote answers the lines, what is due now, what follows, the total and whether the learner is exempt; an unknown
  action, an unknown or malformed hint, and a size that is not an object are 400 naming the field; a missing price is
  503;
  it is rate limited
- the history is newest first and paged by cursor; it holds only the learner's own rows
- each kind of row reads in plain words with the lesson's title when there is one; the words never include an internal
  term; nothing of the ledger's internals (action, hold, meta, key, allocations) is in the answer
- a row about a lesson that was deleted reads without a title
"""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from rest_framework.throttling import SimpleRateThrottle
from support.clock import FakeClock

from credits.ledger import Ledger
from credits.models import CreditBucket, Wallet
from credits.pricing.seed import PriceSeed
from lessons.models import Lesson

pytestmark = pytest.mark.django_db

INTERNAL = ("hold", "ledger", "bucket", "transaction", "settle", "idempotency", "allocation", "authoriz", "wallet")


@pytest.fixture(autouse=True)
def prices(db):
    PriceSeed().apply()


@pytest.fixture
def real():
    """A ledger on the system clock, which is the one the views use."""
    return Ledger()


def in_days(days):
    return datetime.now(UTC) + timedelta(days=days)


class TestWallet:
    URL = "/api/credits/wallet"

    def test_it_needs_a_signed_in_learner(self, api_client):
        assert api_client.get(self.URL).status_code == 401

    def test_a_new_learner_has_nothing_and_the_read_makes_no_wallet(self, signed_in_client, user):
        body = signed_in_client.get(self.URL).json()

        assert body == {"balance": 0, "held": 0, "buckets": [], "next_expiry": None, "exempt": False}
        assert not Wallet.objects.filter(user=user).exists()

    def test_it_gives_the_balance_what_is_held_and_the_credits_in_the_order_they_will_be_spent(
        self, signed_in_client, user, real
    ):
        real.grant(user, "signup", 30, "g1")
        real.grant(user, "daily", 5, "g2", expires_at=in_days(60))
        real.grant(user, "weekly_streak", 10, "g3", expires_at=in_days(3))
        real.place_hold(user, 4, "lesson.create", "h1", subject_id=uuid.uuid4())

        body = signed_in_client.get(self.URL).json()

        assert (body["balance"], body["held"]) == (41, 4)
        assert [(b["source"], b["remaining"]) for b in body["buckets"]] == [
            ("weekly_streak", 6),
            ("daily", 5),
            ("signup", 30),
        ]
        assert body["buckets"][2]["expires_at"] is None and body["buckets"][0]["expires_at"] is not None
        assert body["next_expiry"]["credits"] == 6 and body["next_expiry"]["at"] == body["buckets"][0]["expires_at"]

    def test_lapsed_empty_and_revoked_credits_are_left_out(self, signed_in_client, user, real):
        past = FakeClock(datetime.now(UTC) - timedelta(days=10))
        Ledger(clock=past).grant(user, "daily", 5, "old", expires_at=past.now() + timedelta(days=1))
        real.grant(user, "daily", 3, "spent", expires_at=in_days(1))
        real.debit(user, 3, "x", "d1")
        real.grant(user, "purchase", 8, "bought", expires_at=in_days(30))
        CreditBucket.objects.filter(source="purchase").update(revoked_at=datetime.now(UTC))
        real.grant(user, "signup", 7, "live")

        body = signed_in_client.get(self.URL).json()

        assert body["balance"] == 7 and [b["source"] for b in body["buckets"]] == ["signup"]

    def test_it_shows_whether_the_learner_is_exempt(self, signed_in_client, user, real):
        real.grant(user, "signup", 1, "g")
        Wallet.objects.filter(user=user).update(credits_exempt=True)

        assert signed_in_client.get(self.URL).json()["exempt"] is True

    def test_another_learners_credits_are_not_shown(self, signed_in_client, other_user, real):
        real.grant(other_user, "signup", 99, "theirs")

        assert signed_in_client.get(self.URL).json()["balance"] == 0


class TestQuote:
    URL = "/api/credits/quote"
    CHECK = {"entry": "diagnostic", "intent": "lesson", "origin": "direct", "covers": "diagnostic"}

    def post(self, client, action="lesson.create", size=None, **extra):
        body = {"action": action, "size": self.CHECK if size is None else size, **extra}
        return client.post(self.URL, body, format="json")

    def test_it_needs_a_signed_in_learner(self, api_client):
        assert self.post(api_client).status_code == 401

    def test_it_answers_the_lines_what_is_due_now_what_follows_and_the_total(self, signed_in_client):
        body = self.post(signed_in_client).json()

        assert body["lines"] == [{"key": "lesson.check", "label": "Quick check", "credits": 3}]
        assert (body["due_now"], body["later"], body["total"]) == (3, 7, 10)
        assert body["later_lines"] == [
            {"key": "lesson.rest", "label": "Your lesson, after the Quick check", "credits": 7}
        ]
        assert body["exempt"] is False and body["action"] == "lesson.create"

    def test_an_action_with_nothing_after_it_has_nothing_later(self, signed_in_client):
        body = self.post(signed_in_client, "test.retake", {"question_count": 10, "attempt_no": 2}).json()

        assert (body["due_now"], body["later"], body["total"], body["later_lines"]) == (2, 0, 2, [])

    def test_it_says_when_the_learner_is_exempt_and_still_shows_the_price(self, signed_in_client, user, real):
        real.grant(user, "signup", 1, "g")
        Wallet.objects.filter(user=user).update(credits_exempt=True)

        body = self.post(signed_in_client).json()

        assert body["exempt"] is True and body["due_now"] == 3

    def test_a_quote_makes_no_wallet_and_no_hold(self, signed_in_client, user):
        self.post(signed_in_client)

        from credits.models import CreditHold

        assert not Wallet.objects.filter(user=user).exists() and not CreditHold.objects.exists()

    @pytest.mark.parametrize(
        ("action", "size", "field"),
        [
            ("lesson.invented", {}, "action"),
            ("", {}, "action"),
            ("lesson.create", {"entry": "teleport", "intent": "lesson", "origin": "direct"}, "size"),
            ("lesson.create", {}, "size"),
            ("lesson.create", {"entry": "diagnostic", "intent": "lesson", "origin": "direct", "free": 1}, "size"),
            ("lesson.continue", {"choice": "lesson", "sheets": "many"}, "size"),
            ("quiz.create", {"num_questions": 7, "source_type": "topic", "level_mode": "self_rating"}, "size"),
            ("sheet.generate", {"sheets": True, "grounding": "none"}, "size"),
            ("lesson.create", ["not", "an", "object"], "size"),
            ("lesson.create", "text", "size"),
        ],
    )
    def test_anything_that_is_not_a_real_question_is_400_and_names_the_field(
        self, signed_in_client, action, size, field
    ):
        response = self.post(signed_in_client, action, size)

        assert response.status_code == 400 and field in response.json()["fields"]

    def test_a_missing_size_is_the_same_as_an_empty_one(self, signed_in_client):
        response = signed_in_client.post(self.URL, {"action": "lesson.create"}, format="json")

        assert response.status_code == 400 and "size" in response.json()["fields"]

    def test_a_missing_price_is_503_never_free(self, signed_in_client):
        from credits.models import ActionPrice

        ActionPrice.objects.filter(key="lesson.check").delete()

        response = self.post(signed_in_client)

        assert response.status_code == 503 and response.json()["code"] == "price_unavailable"

    def test_it_is_rate_limited(self, signed_in_client, monkeypatch):
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "credits_quote", "2/min")

        statuses = [self.post(signed_in_client).status_code for _ in range(3)]

        assert statuses == [200, 200, 429]


class TestTransactions:
    URL = "/api/credits/transactions"

    def test_it_needs_a_signed_in_learner(self, api_client):
        assert api_client.get(self.URL).status_code == 401

    def test_a_new_learner_has_an_empty_history(self, signed_in_client):
        body = signed_in_client.get(self.URL).json()

        assert body["results"] == [] and body["next"] is None

    def test_it_is_newest_first_and_only_the_learners_own(self, signed_in_client, user, other_user, real):
        real.grant(user, "signup", 30, "a")
        real.grant(other_user, "signup", 99, "theirs")
        real.grant(user, "daily", 1, "b")

        body = signed_in_client.get(self.URL).json()

        assert [r["text"] for r in body["results"]] == [
            "Earned 1 credit for studying today",
            "Welcome gift: 30 credits",
        ]
        assert [r["balance_after"] for r in body["results"]] == [31, 30]

    def test_it_pages_by_cursor(self, signed_in_client, user, real):
        for n in range(5):
            real.grant(user, "daily", 1, f"g{n}")

        first = signed_in_client.get(self.URL, {"page_size": 2}).json()
        second = signed_in_client.get(first["next"]).json()

        assert len(first["results"]) == 2 and len(second["results"]) == 2 and second["next"] is not None
        ids = [r["id"] for r in first["results"] + second["results"]]
        assert ids == sorted(ids, reverse=True) and len(set(ids)) == 4

    def test_each_kind_of_row_reads_in_plain_words_with_the_lessons_title(self, signed_in_client, user, real, lesson):
        import uuid as _uuid

        real.grant(user, "purchase", 100, "p", expires_at=in_days(300), purchase_id=_uuid.uuid4())
        real.grant(user, "subscription", 50, "s", expires_at=in_days(20))
        real.grant(user, "weekly_streak", 10, "w", expires_at=in_days(90))
        real.grant(user, "monthly_streak", 10, "m", expires_at=in_days(90))
        real.grant(user, "admin_grant", 4, "a")
        hold = real.place_hold(user, 3, "lesson.create", "h1", subject_kind="lesson", subject_id=lesson.id).hold
        real.commit(hold.pk)
        refused = real.place_hold(user, 2, "lesson.continue", "h2", subject_kind="lesson", subject_id=lesson.id).hold
        real.release(refused.pk)
        real.place_hold(user, 0, "test.retake", "h3", subject_kind="test_attempt", subject_id=uuid.uuid4())
        real.debit(user, 1, "streak_repair", "r", type="repair")
        real.debit(user, 1, "x", "d")
        real.adjust(user, 5, "adj1", reason="Goodwill", actor="staff@example.com")
        real.adjust(user, -2, "adj2", reason="Mistake", actor="staff@example.com")
        past = FakeClock(datetime.now(UTC) - timedelta(days=5))
        Ledger(clock=past).grant(user, "daily", 6, "lapsing", expires_at=past.now() + timedelta(days=1))
        real.expire_due(user)

        results = signed_in_client.get(self.URL, {"page_size": 100}).json()["results"]

        texts = {r["text"] for r in results}
        title = lesson.topic
        assert {
            "Bought 100 credits",
            "50 credits from your plan",
            "Earned 10 credits for a 7-day streak",
            "Earned 10 credits for a 28-day streak",
            "4 credits added by Socra",
            f"Reserved 3 credits for “{title}”",
            f"Used 3 credits for “{title}”",
            f"Reserved 2 credits for “{title}”",
            f"Returned 2 credits for “{title}”",
            "No credits needed for this",
            "Used 1 credit to repair your streak",
            "Used 1 credit",
            "5 credits added by Socra",
            "2 credits taken off by Socra",
            "6 credits expired",
        } <= texts
        kinds = {r["kind"] for r in results}
        assert kinds == {"bought", "earned", "reserved", "used", "returned", "adjusted", "expired"}

    def test_the_words_never_use_an_internal_term(self, signed_in_client, user, real, lesson):
        real.grant(user, "signup", 30, "g")
        hold = real.place_hold(user, 3, "lesson.create", "h", subject_kind="lesson", subject_id=lesson.id).hold
        real.release(hold.pk)
        real.adjust(user, 1, "adj", reason="r", actor="staff")

        results = signed_in_client.get(self.URL).json()["results"]

        for row in results:
            text = row["text"].lower()
            assert not any(word in text for word in INTERNAL), row["text"]

    def test_nothing_of_the_ledgers_insides_is_in_the_answer(self, signed_in_client, user, real, lesson):
        hold = real.place_hold(user, 0, "lesson.create", "h", subject_kind="lesson", subject_id=lesson.id).hold
        real.commit(hold.pk)

        results = signed_in_client.get(self.URL).json()["results"]

        assert set(results[0]) == {"id", "kind", "text", "amount", "balance_after", "created_at", "subject"}
        raw = json.dumps(results)
        assert str(hold.pk) not in raw and "idempotency" not in raw and "lesson.create" not in raw

    def test_a_row_names_its_lesson_so_the_screen_can_link_it(self, signed_in_client, user, real, lesson):
        real.grant(user, "signup", 10, "g")
        real.place_hold(user, 3, "lesson.create", "h", subject_kind="lesson", subject_id=lesson.id)

        row = signed_in_client.get(self.URL).json()["results"][0]

        assert row["subject"] == {"kind": "lesson", "id": str(lesson.id), "title": lesson.topic}

    def test_a_row_about_a_lesson_that_was_deleted_reads_without_a_title(
        self, signed_in_client, user, real, make_lesson
    ):
        gone = make_lesson(topic="Gone")
        real.grant(user, "signup", 10, "g")
        hold = real.place_hold(user, 3, "lesson.create", "h", subject_kind="lesson", subject_id=gone.id).hold
        real.commit(hold.pk)
        Lesson.objects.filter(pk=gone.pk).delete()

        results = signed_in_client.get(self.URL).json()["results"]

        assert results[0]["text"] == "Used 3 credits" and results[0]["subject"] is None

    def test_a_retake_names_the_lesson_its_attempt_belongs_to(self, signed_in_client, user, real, lesson):
        from lessons.models import TestSubmission

        attempt = TestSubmission.objects.create(lesson=lesson, attempt_no=2, status="generating", questions=[])
        real.grant(user, "signup", 10, "g")
        real.place_hold(user, 2, "test.retake", "h", subject_kind="test_attempt", subject_id=attempt.pk)

        row = signed_in_client.get(self.URL).json()["results"][0]

        assert row["text"] == f"Reserved 2 credits for “{lesson.topic}”"
        assert row["subject"]["kind"] == "lesson" and row["subject"]["id"] == str(lesson.id)

    def test_a_quiz_retake_names_the_quiz(self, signed_in_client, user, real, quiz, make_attempt):
        attempt = make_attempt(quiz, status="generating", questions=[])
        real.grant(user, "signup", 10, "g")
        real.place_hold(user, 1, "quiz.retake", "h", subject_kind="quiz_attempt", subject_id=attempt.pk)

        row = signed_in_client.get(self.URL).json()["results"][0]

        assert row["subject"]["kind"] == "quiz" and row["subject"]["id"] == str(quiz.id)
        assert row["subject"]["title"] == quiz.topic
