"""Unit under test: `credits.plans.pricing.PlanPricing` and `PlanTerms` (credits plan T20, D1): what a purchase costs
and
gives, always computed on the server from the plan.

Why: the client sends a plan and a quantity (or a number of credits), never a price. Every rule about what may be
bought is
here: the smallest and largest one-time amount, how many weeks at once, and that the monthly plans are bought one at
a time.
A purchase that breaks a rule must be refused before any money moves.

Use cases:
- one-time credits cost the plan's price a credit, with the smallest and largest amount from the settings (10 and
  5,000), and
  are bought once at a time; below, above, fractional, boolean and text amounts are refused as `invalid_amount`
- Weekly Pro costs 4,900 paise a week and may be bought 1 to 12 weeks at once; 0, 13 and a non-number are refused
- Monthly Pro and Pro Plus are bought one at a time
- a recurring plan takes no credit amount and a one-time purchase takes no quantity other than 1
- the numbers are whole: paise and credits, never a float
- the answer says how many periods the purchase makes (none for one-time credits)
- a plan row is read into its terms as it is, one-time credits included (`PurchaseDesk.terms_of`)
"""

import pytest

from credits.models import Plan
from credits.plans.desk import PurchaseDesk
from credits.plans.errors import InvalidPlanRequest
from credits.plans.pricing import PlanPricing, PlanTerms

ONE_TIME = PlanTerms(
    "one_time", "One-time credits", credits=0, period_days=365, price_paise=100, max_quantity=1, one_time=True
)
WEEKLY = PlanTerms(
    "weekly_pro", "Weekly Pro", credits=100, period_days=7, price_paise=4900, max_quantity=12, one_time=False
)
MONTHLY = PlanTerms(
    "monthly_pro", "Monthly Pro", credits=500, period_days=28, price_paise=19900, max_quantity=1, one_time=False
)
PLUS = PlanTerms("pro_plus", "Pro Plus", credits=750, period_days=28, price_paise=27900, max_quantity=1, one_time=False)
LIMITS = {"minimum": 10, "maximum": 5000}


def price(terms, **kwargs):
    return PlanPricing().price(terms, **LIMITS, **kwargs)


class TestOneTimeCredits:
    @pytest.mark.parametrize(("credits", "paise"), [(10, 1000), (11, 1100), (250, 25000), (5000, 500000)])
    def test_the_price_is_the_plans_price_a_credit(self, credits, paise):
        priced = price(ONE_TIME, credits=credits)

        assert (priced.credits, priced.amount_paise, priced.periods, priced.quantity) == (credits, paise, 0, 1)

    @pytest.mark.parametrize("credits", [9, 0, -10, 5001, 100000, 12.5, "50", None, True, [10]])
    def test_an_amount_outside_the_limits_or_not_a_whole_number_is_refused(self, credits):
        with pytest.raises(InvalidPlanRequest) as refused:
            price(ONE_TIME, credits=credits)

        assert refused.value.get_codes() == "invalid_amount" and refused.value.status_code == 400

    def test_the_limits_are_whatever_the_settings_say(self):
        assert PlanPricing().price(ONE_TIME, credits=3, minimum=1, maximum=3).amount_paise == 300
        with pytest.raises(InvalidPlanRequest):
            PlanPricing().price(ONE_TIME, credits=4, minimum=1, maximum=3)

    @pytest.mark.parametrize("quantity", [0, 2, 12])
    def test_it_is_bought_once_at_a_time(self, quantity):
        with pytest.raises(InvalidPlanRequest):
            price(ONE_TIME, credits=10, quantity=quantity)

    def test_the_price_a_credit_comes_from_the_plan(self):
        dearer = PlanTerms(
            "one_time", "One-time", credits=0, period_days=365, price_paise=150, max_quantity=1, one_time=True
        )

        assert price(dearer, credits=10).amount_paise == 1500


class TestRecurringPlans:
    @pytest.mark.parametrize("weeks", range(1, 13))
    def test_weekly_pro_costs_4900_paise_a_week(self, weeks):
        priced = price(WEEKLY, quantity=weeks)

        assert (priced.quantity, priced.amount_paise, priced.periods, priced.credits) == (weeks, 4900 * weeks, weeks, 0)

    @pytest.mark.parametrize("weeks", [0, -1, 13, 100, 2.5, "3", None, True])
    def test_weeks_outside_one_to_twelve_are_refused(self, weeks):
        with pytest.raises(InvalidPlanRequest) as refused:
            price(WEEKLY, quantity=weeks)

        assert refused.value.get_codes() == "invalid_amount"

    @pytest.mark.parametrize(("terms", "paise"), [(MONTHLY, 19900), (PLUS, 27900)])
    def test_the_monthly_plans_are_bought_one_at_a_time(self, terms, paise):
        priced = price(terms)

        assert (priced.quantity, priced.amount_paise, priced.periods) == (1, paise, 1)
        with pytest.raises(InvalidPlanRequest):
            price(terms, quantity=2)

    def test_a_recurring_plan_takes_no_credit_amount(self):
        with pytest.raises(InvalidPlanRequest) as refused:
            price(WEEKLY, quantity=2, credits=500)

        assert refused.value.get_codes() == "invalid_amount"

    def test_the_numbers_are_whole(self):
        priced = price(WEEKLY, quantity=3)

        assert all(type(n) is int for n in (priced.amount_paise, priced.quantity, priced.periods, priced.credits))


def test_the_terms_are_made_from_a_plan_row_and_know_whether_they_are_one_time():
    assert ONE_TIME.one_time and not WEEKLY.one_time


@pytest.mark.django_db
class TestTermsOfAPlanRow:
    def test_a_plan_row_is_read_into_its_terms_as_it_is(self):
        from credits.plans.seed import PlanSeed

        PlanSeed().apply()

        assert PurchaseDesk.terms_of(Plan.objects.get(key="weekly_pro")) == WEEKLY
        assert PurchaseDesk.terms_of(Plan.objects.get(key="monthly_pro")) == MONTHLY
        assert PurchaseDesk.terms_of(Plan.objects.get(key="pro_plus")) == PLUS
        assert PurchaseDesk.terms_of(Plan.objects.get(key="one_time")) == ONE_TIME
