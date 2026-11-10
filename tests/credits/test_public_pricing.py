"""Unit under test: `GET /api/public/pricing` (`credits.pricing.public.PublicPricing`, served by
`marketing.views.PublicPricingView`).

Why: the landing page shows prices to people who are not signed in, and a price on a public page that differs from the
price charged is the worst kind of wrong. So the page holds no number of its own: everything it shows is read here, from
the same rows the checkout and the credit gate read (`Plan`, `ActionPrice`, `CreditSettings`) and priced by the same
rules (`PriceRules`), and a price changed in the console is the price on the page at once. "About N lessons" is worked
out here, once, so the page and the API cannot disagree.

Use cases:
- it needs no sign-in, carries only public numbers (no keys of rows, no learner data) and may be cached by the browser
  for a short time
- the plans are the active recurring ones, in the console's order, with credits, period, price in paise, the most that
  can be bought at once, the price of one credit, and about how many full lessons the credits make (whole lessons, never
  rounded up)
- the one-time rules (price of a credit, smallest and largest amount, how long they last) come from the one-time plan
  and the settings; no one-time plan means none shown
- the sign-up grant, the daily credit, the weekly and 28-day streak bonuses and how long earned credits last come from
  the settings, with about how many lessons the sign-up grant makes
- how many questions a Quick check has (five bands of the lesson settings' questions a band) is read from the lesson
  settings, so the page never states a count the product does not use
- the prices a visitor is shown (a full lesson, a retake, a study sheet, a quick quiz) are the live `ActionPrice` rows
  priced through the same rules the gate uses; a sheet and a quiz are a range from least to most
- a price edited in the console, a plan switched off or edited, and a settings edit show at once, despite the cache
- a price with no live row is left out (null) and never shown as free, and does not stop the rest being shown
- a second read within the cache window makes no database query
- each client address has its own limit (60 a minute by default), and past it the answer is 429 `throttled`
"""

from datetime import UTC, datetime

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.throttling import SimpleRateThrottle

from credits.models import CreditSettings, Plan
from credits.plans.seed import PlanSeed
from credits.pricing.book import PriceCatalog
from credits.pricing.seed import PriceSeed
from lessons.models import FlowSettings

pytestmark = pytest.mark.django_db

URL = "/api/public/pricing"
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def seeded(db):
    PlanSeed().apply()
    PriceSeed().apply()
    CreditSettings.load()


def get(api_client) -> dict:
    return api_client.get(URL).json()


def plan(body: dict, key: str) -> dict:
    return next(p for p in body["plans"] if p["key"] == key)


def test_it_needs_no_sign_in_and_may_be_kept_briefly_by_the_browser(api_client):
    response = api_client.get(URL)

    assert response.status_code == 200
    assert "public" in response["Cache-Control"] and "max-age=" in response["Cache-Control"]
    assert set(response.json()) == {
        "plans", "one_time", "signup_credits", "signup_about_lessons", "daily_credits", "weekly_streak_bonus",
        "monthly_streak_bonus", "bonus_valid_days", "lesson_credits", "retake_credits", "sheet_credits",
        "quiz_credits", "quick_check_questions",
    }  # fmt: skip


def test_the_plans_are_the_active_recurring_ones_with_their_terms(api_client):
    body = get(api_client)

    assert [p["key"] for p in body["plans"]] == ["weekly_pro", "monthly_pro", "pro_plus"]
    assert plan(body, "weekly_pro") == {
        "key": "weekly_pro", "name": "Weekly Pro", "credits": 100, "period_days": 7, "price_paise": 4900,
        "max_quantity": 12, "price_paise_per_credit": 49.0, "about_lessons": 10,
    }  # fmt: skip
    assert plan(body, "monthly_pro")["price_paise_per_credit"] == 39.8
    assert (plan(body, "pro_plus")["about_lessons"], plan(body, "pro_plus")["price_paise_per_credit"]) == (75, 37.2)


def test_about_lessons_is_credits_over_the_lesson_price_rounded_down(api_client):
    PriceCatalog().revise("lesson.full", 7, by="root@example.com", now=NOW)

    body = get(api_client)

    assert [plan(body, k)["about_lessons"] for k in ("weekly_pro", "monthly_pro", "pro_plus")] == [14, 71, 107]
    assert body["signup_about_lessons"] == 4  # 30 credits at 7 a lesson


def test_the_one_time_rules_come_from_the_plan_and_the_settings(api_client):
    body = get(api_client)

    assert body["one_time"] == {
        "price_paise_per_credit": 100,
        "min_credits": 10,
        "max_credits": 5000,
        "valid_days": 365,
    }


def test_no_one_time_plan_means_no_one_time_rules(api_client):
    one_time = Plan.objects.get(key="one_time")
    one_time.active = False
    one_time.save()

    assert get(api_client)["one_time"] is None


def test_the_signup_grant_and_the_earning_amounts_come_from_the_settings(api_client):
    body = get(api_client)

    assert (body["signup_credits"], body["signup_about_lessons"]) == (30, 3)
    assert (body["daily_credits"], body["weekly_streak_bonus"], body["monthly_streak_bonus"]) == (1, 10, 10)
    assert body["bonus_valid_days"] == 90


def test_the_quick_check_length_is_read_from_the_lesson_settings_and_follows_an_edit(api_client):
    assert get(api_client)["quick_check_questions"] == 10  # 5 bands, 2 questions a band

    flow = FlowSettings.load()
    flow.diagnostic_questions_per_band = 3
    flow.save()

    assert get(api_client)["quick_check_questions"] == 15


def test_the_prices_a_visitor_sees_are_the_live_rows_through_the_gates_own_rules(api_client):
    body = get(api_client)

    assert body["lesson_credits"] == 10 and body["retake_credits"] == 2
    assert body["sheet_credits"] == {"min": 2, "max": 3}  # a sheet, and a sheet built from a lesson's pages
    assert body["quiz_credits"] == {"min": 1, "max": 4}  # 5 questions, and 20 or more from lessons


def test_a_price_edited_in_the_console_shows_at_once(api_client):
    assert get(api_client)["lesson_credits"] == 10

    PriceCatalog().revise("lesson.full", 12, by="root@example.com", now=NOW)
    PriceCatalog().revise("sheet.each", 3, by="root@example.com", now=NOW)
    PriceCatalog().revise("quiz.tier_20", 5, by="root@example.com", now=NOW)
    body = get(api_client)

    assert body["lesson_credits"] == 12
    assert body["sheet_credits"] == {"min": 3, "max": 4}
    assert body["quiz_credits"] == {"min": 1, "max": 6}
    assert plan(body, "monthly_pro")["about_lessons"] == 41  # 500 credits at 12 a lesson


def test_a_plan_switched_off_or_edited_shows_at_once(api_client):
    assert [p["key"] for p in get(api_client)["plans"]] == ["weekly_pro", "monthly_pro", "pro_plus"]

    weekly = Plan.objects.get(key="weekly_pro")
    weekly.active = False
    weekly.save()
    assert [p["key"] for p in get(api_client)["plans"]] == ["monthly_pro", "pro_plus"]

    edited = Plan.objects.get(key="monthly_pro")
    edited.price_paise = 17900
    edited.save()
    assert plan(get(api_client), "monthly_pro")["price_paise"] == 17900


def test_a_settings_edit_shows_at_once(api_client):
    assert get(api_client)["signup_credits"] == 30

    settings = CreditSettings.load()
    settings.signup_credits, settings.daily_credits = 50, 2
    settings.save()
    body = get(api_client)

    assert (body["signup_credits"], body["daily_credits"], body["signup_about_lessons"]) == (50, 2, 5)


def test_a_price_with_no_live_row_is_left_out_not_shown_as_free(api_client):
    PriceCatalog().deactivate("test.retake", by="root@example.com", now=NOW)
    PriceCatalog().deactivate("sheet.each", by="root@example.com", now=NOW)

    body = get(api_client)

    assert body["retake_credits"] is None and body["sheet_credits"] is None
    assert body["lesson_credits"] == 10 and body["quiz_credits"] == {"min": 1, "max": 4}


def test_with_no_lesson_price_no_lessons_are_promised(api_client):
    PriceCatalog().deactivate("lesson.full", by="root@example.com", now=NOW)

    body = get(api_client)

    assert body["lesson_credits"] is None and body["signup_about_lessons"] is None
    assert all(p["about_lessons"] is None for p in body["plans"])


def test_a_free_lesson_does_not_divide_by_zero(api_client):
    PriceCatalog().revise("lesson.full", 0, by="root@example.com", now=NOW)

    body = get(api_client)

    assert body["lesson_credits"] == 0 and body["signup_about_lessons"] is None


def test_a_second_read_makes_no_database_query(api_client):
    get(api_client)

    with CaptureQueriesContext(connection) as queries:
        api_client.get(URL)

    assert len(queries) == 0


def test_each_client_address_has_its_own_limit(api_client, monkeypatch):
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "public_pages", "2/min")

    first = [api_client.get(URL, REMOTE_ADDR="10.0.0.1").status_code for _ in range(3)]

    assert first == [200, 200, 429]
    assert api_client.get(URL, REMOTE_ADDR="10.0.0.2").status_code == 200
