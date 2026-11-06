"""Unit under test: `GET /api/credits/plans` (credits plan §8.1).

Why: this is what the buy page will be built from, so it must carry the prices and the rules that the server will
enforce when
an order is made (and never a number the server does not hold to), and the learner's own periods, so the page can say
what is
running and what is waiting. It must be private to the learner and must not make anything.

Use cases:
- it needs a signed-in learner
- it lists the plans that are switched on, in order, with their credits, length, price in paise and the most that can be
  bought at once; a plan switched off is not offered
- it carries the one-time rules (smallest, largest, price a credit, how long the credits last) from the settings and
  the plan
- a learner with no plan has no periods and a free queue; one with plans sees the running and waiting periods soonest
  first,
  with the plan's name, and how many are open against the limit
- periods that ended are not listed; another learner's periods are never shown
- reading starts a period that is due (the credits are there when the page is), and makes no wallet for a learner
  without one
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from credits.ledger import Ledger
from credits.models import CreditBucket, CreditSettings, Plan, PlanPeriod, Wallet
from credits.plans.desk import PurchaseDesk
from credits.plans.fulfilment import PlanFulfilment
from credits.plans.seed import PlanSeed

pytestmark = pytest.mark.django_db

URL = "/api/credits/plans"


@pytest.fixture(autouse=True)
def plans(db):
    PlanSeed().apply()


def buy(user, plan, **kwargs):
    ledger = Ledger()  # on the system clock, as the view is
    return PlanFulfilment(ledger=ledger).fulfil(PurchaseDesk(ledger=ledger).open(user, plan, **kwargs))


def test_it_needs_a_signed_in_learner(api_client):
    assert api_client.get(URL).status_code == 401


def test_it_lists_the_plans_that_are_on_with_their_terms(signed_in_client):
    body = signed_in_client.get(URL).json()

    assert [p["key"] for p in body["plans"]] == ["one_time", "weekly_pro", "monthly_pro", "pro_plus"]
    by_key = {p["key"]: p for p in body["plans"]}
    assert by_key["weekly_pro"] == {
        "key": "weekly_pro", "name": "Weekly Pro", "kind": "recurring", "credits": 100, "period_days": 7,
        "price_paise": 4900, "max_quantity": 12,
    }  # fmt: skip
    monthly = by_key["monthly_pro"]
    assert (monthly["credits"], monthly["period_days"], monthly["price_paise"]) == (
        500, 28, 19900
    )  # fmt: skip
    assert (by_key["pro_plus"]["credits"], by_key["pro_plus"]["price_paise"]) == (750, 27900)
    assert by_key["one_time"]["kind"] == "one_time"


def test_a_plan_that_is_switched_off_is_not_offered(signed_in_client):
    Plan.objects.filter(key="pro_plus").update(active=False)

    assert "pro_plus" not in [p["key"] for p in signed_in_client.get(URL).json()["plans"]]


def test_it_carries_the_one_time_rules(signed_in_client):
    CreditSettings.objects.update_or_create(pk=1, defaults={"min_one_time_credits": 20, "purchased_valid_days": 300})

    rules = signed_in_client.get(URL).json()["one_time"]

    assert rules == {"min_credits": 20, "max_credits": 5000, "price_paise_per_credit": 100, "valid_days": 300}


def test_a_learner_with_no_plan_has_no_periods_and_a_free_queue(signed_in_client, user):
    body = signed_in_client.get(URL).json()

    assert body["periods"] == [] and body["queue"] == {"open": 0, "limit": 12}
    assert not Wallet.objects.filter(user=user).exists()


def test_the_running_and_waiting_periods_are_listed_soonest_first(signed_in_client, user):
    buy(user, "weekly_pro", quantity=2)
    buy(user, "monthly_pro")

    body = signed_in_client.get(URL).json()

    assert [(p["plan"], p["plan_name"], p["status"], p["credits"]) for p in body["periods"]] == [
        ("weekly_pro", "Weekly Pro", "active", 100),
        ("weekly_pro", "Weekly Pro", "queued", 100),
        ("monthly_pro", "Monthly Pro", "queued", 500),
    ]
    starts = [p["starts_at"] for p in body["periods"]]
    assert starts == sorted(starts) and body["queue"]["open"] == 3


def test_periods_that_ended_are_not_listed(signed_in_client, user):
    buy(user, "weekly_pro", quantity=1)
    PlanPeriod.objects.filter(user=user).update(
        starts_at=timezone.now() - 8 * timedelta(days=1), ends_at=timezone.now() - timedelta(days=1)
    )

    body = signed_in_client.get(URL).json()

    assert body["periods"] == [] and body["queue"]["open"] == 0


def test_another_learners_periods_are_not_shown(signed_in_client, other_user):
    buy(other_user, "monthly_pro")

    assert signed_in_client.get(URL).json()["periods"] == []


def test_the_limit_is_the_setting(signed_in_client):
    CreditSettings.objects.update_or_create(pk=1, defaults={"max_queued_periods": 5})

    assert signed_in_client.get(URL).json()["queue"]["limit"] == 5


def test_reading_starts_a_period_that_is_due(signed_in_client, user):
    buy(user, "weekly_pro", quantity=2)
    now = timezone.now()
    PlanPeriod.objects.filter(user=user, position=1).update(
        starts_at=now - 8 * timedelta(days=1), ends_at=now - timedelta(days=1)
    )
    PlanPeriod.objects.filter(user=user, position=2).update(
        starts_at=now - timedelta(days=1), ends_at=now + 6 * timedelta(days=1)
    )
    CreditBucket.objects.filter(user=user, source="subscription").update(expires_at=now - timedelta(days=1))

    body = signed_in_client.get(URL).json()

    assert [p["status"] for p in body["periods"]] == ["active"]
    assert signed_in_client.get("/api/credits/wallet").json()["balance"] == 100
