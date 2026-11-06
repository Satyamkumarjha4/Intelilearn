"""Unit under test: `GET /api/credits/notices` and `GET /api/credits/balance` (credits plan §8.1, §5.10).

Why: the header shows a balance on every page, so its endpoint must be light, private and rate limited, and must say the
same as the wallet. The notices are what the banner and the wallet page say about credits about to lapse; they must come
from `ExpiryNotices` and nothing else, so the number on the header chip and the list on the wallet cannot disagree.

Use cases:
- both need a signed-in learner (401), and a read makes no wallet
- the notices are a list of the learner's own, soonest first, each with an id, the day, the days left, the credits and
  the words; a learner with nothing about to lapse gets an empty list
- the balance is what the wallet shows, with what is reserved for work under way and how many notices there are; it is
  the same number the wallet gives
- reading the balance starts a plan period that is due, so the chip is right the moment a week starts
- another learner's credits are never counted
- the balance is rate limited, under its own scope
"""

from datetime import UTC, datetime, timedelta

import pytest
from rest_framework.throttling import SimpleRateThrottle

from credits.ledger import Ledger
from credits.models import Wallet
from credits.plans.desk import PurchaseDesk
from credits.plans.fulfilment import PlanFulfilment
from credits.plans.seed import PlanSeed

pytestmark = pytest.mark.django_db

NOTICES, BALANCE, WALLET = "/api/credits/notices", "/api/credits/balance", "/api/credits/wallet"


@pytest.fixture
def real():
    """A ledger on the system clock, which is the one the views use."""
    return Ledger()


def in_days(days):
    return datetime.now(UTC) + timedelta(days=days)


class TestAccess:
    @pytest.mark.parametrize("url", [NOTICES, BALANCE])
    def test_they_need_a_signed_in_learner(self, api_client, url):
        assert api_client.get(url).status_code == 401

    @pytest.mark.parametrize("url", [NOTICES, BALANCE])
    def test_a_read_makes_no_wallet(self, signed_in_client, user, url):
        assert signed_in_client.get(url).status_code == 200
        assert not Wallet.objects.filter(user=user).exists()


class TestNotices:
    def test_a_learner_with_nothing_about_to_lapse_gets_an_empty_list(self, signed_in_client, user, real):
        real.grant(user, "signup", 30, "s")
        real.grant(user, "daily", 5, "d", expires_at=in_days(60))

        assert signed_in_client.get(NOTICES).json() == {"notices": []}

    def test_it_lists_the_learners_own_soonest_first_with_the_words(self, signed_in_client, user, other_user, real):
        real.grant(user, "daily", 5, "far", expires_at=in_days(4))
        real.grant(user, "weekly_streak", 10, "near", expires_at=in_days(1))
        real.grant(other_user, "daily", 99, "not-mine", expires_at=in_days(1))

        found = signed_in_client.get(NOTICES).json()["notices"]

        assert [(n["days_left"], n["credits"]) for n in found] == [(1, 10), (4, 5)]
        assert found[0]["text"] == "10 credits will run out tomorrow."
        assert set(found[0]) == {"id", "expires_on", "days_left", "credits", "text"}
        assert found[0]["id"] == f"expiry-{found[0]['expires_on']}"


class TestBalance:
    def test_a_new_learner_has_nothing(self, signed_in_client):
        assert signed_in_client.get(BALANCE).json() == {"balance": 0, "reserved": 0, "notices": 0}

    def test_it_gives_the_balance_what_is_reserved_and_the_number_of_notices(self, signed_in_client, user, real):
        real.grant(user, "signup", 30, "s")
        real.grant(user, "daily", 5, "d", expires_at=in_days(2))
        real.place_hold(user, 4, "lesson.create", "h1")

        assert signed_in_client.get(BALANCE).json() == {"balance": 31, "reserved": 4, "notices": 1}

    def test_it_agrees_with_the_wallet(self, signed_in_client, user, real):
        real.grant(user, "signup", 30, "s")
        real.grant(user, "daily", 5, "d", expires_at=in_days(2))
        real.place_hold(user, 4, "lesson.create", "h1")

        chip, wallet = signed_in_client.get(BALANCE).json(), signed_in_client.get(WALLET).json()

        assert (chip["balance"], chip["reserved"]) == (wallet["balance"], wallet["reserved"])

    def test_another_learners_credits_are_not_counted(self, signed_in_client, other_user, real):
        real.grant(other_user, "daily", 50, "g", expires_at=in_days(1))

        assert signed_in_client.get(BALANCE).json() == {"balance": 0, "reserved": 0, "notices": 0}

    def test_it_starts_a_plan_period_that_is_due(self, signed_in_client, user):
        PlanSeed().apply()
        ledger = Ledger()
        done = PlanFulfilment(ledger=ledger).fulfil(PurchaseDesk(ledger=ledger).open(user, "weekly_pro", quantity=2))
        assert done is not None
        assert signed_in_client.get(BALANCE).json()["balance"] == 100  # the first week; the second waits

    def test_it_is_rate_limited(self, signed_in_client, monkeypatch):
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "credits_balance", "2/min")

        statuses = [signed_in_client.get(BALANCE).status_code for _ in range(3)]

        assert statuses == [200, 200, 429]
