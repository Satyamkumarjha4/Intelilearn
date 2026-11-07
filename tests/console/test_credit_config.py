"""Unit under test: `/api/console/credits` and its writes (`console.services.credit_config.CreditConfig`; credits plan
§10, D12): the prices with their history, the plans, and the credit settings.

Why: prices and rules decide what every learner pays and earns, so a change must be deliberate, checked by the same
rules the models have, never rewrite history, and be written to the change log with what it was and what it became. A
price is changed by adding a row, so the next hold uses it and a hold already placed does not change.

Use cases:
- one read gives every price with its live value and its history (newest first), the plans, and the settings
- a price edit adds a row, keeps the old one as history, is used by the next quote, and writes the change log with the
  value before and after and who made it; the same price again writes nothing; 0 is a price; a negative or non-number
  is refused; an unknown key is a 404; a key switched off reads as unavailable, not free
- a plan edit changes only what was sent, is checked by the model's rules, and writes before and after; an unknown plan
  is a 404; its key cannot be changed; what was already bought is not changed
- a settings edit is the same: validated by the model, nothing saved when one value is refused, one entry for the change
- a change that changes nothing writes nothing
"""

import pytest
from django.utils import timezone

from console.models import AuditEntry
from credits.models import ActionPrice, CreditSettings, Plan, PlanPurchase
from credits.plans.seed import PlanSeed
from credits.pricing.book import PriceBook
from credits.pricing.seed import PriceSeed

pytestmark = pytest.mark.django_db

URL = "/api/console/credits"


@pytest.fixture(autouse=True)
def seeded(db):
    PriceSeed().apply()
    PlanSeed().apply()


def price(client, key, **body):
    return client.patch(f"{URL}/prices/{key}", body, format="json")


class TestReadingEverything:
    def test_it_gives_prices_with_history_plans_and_settings(self, staff_client):
        body = staff_client.get(URL).json()

        assert set(body) == {"prices", "plans", "settings"}
        assert {p["key"] for p in body["prices"]} >= {"lesson.full", "test.retake"}
        first = next(p for p in body["prices"] if p["key"] == "lesson.full")
        assert first["available"] and first["credits"] == first["history"][0]["credits"] and first["label"]
        assert [p["key"] for p in body["plans"]] == ["one_time", "weekly_pro", "monthly_pro", "pro_plus"]
        assert body["settings"]["signup_credits"] == 30 and "paise_per_credit" not in body["settings"]


class TestPrices:
    def test_an_edit_adds_a_row_keeps_the_old_one_and_is_used_by_the_next_quote(self, staff_client, staff_user):
        before = PriceBook().credits("lesson.full")

        response = price(staff_client, "lesson.full", credits=before + 4)

        body = response.json()
        assert response.status_code == 200 and body["credits"] == before + 4
        assert [h["credits"] for h in body["history"]] == [before + 4, before]
        assert [h["active"] for h in body["history"]] == [True, False]
        assert PriceBook().credits("lesson.full") == before + 4  # the next hold reads the new one
        assert ActionPrice.objects.filter(key="lesson.full").count() == 2
        entry = AuditEntry.objects.get(action="credits.price")
        assert (entry.actor_email, entry.target_id) == (staff_user.email, "lesson.full")
        assert (entry.before["credits"], entry.after["credits"]) == (before, before + 4)

    def test_the_label_can_change_with_it(self, staff_client):
        response = price(staff_client, "lesson.full", credits=11, label="A new lesson")

        assert response.json()["label"] == "A new lesson"

    def test_the_same_price_again_writes_nothing(self, staff_client):
        now = PriceBook().credits("lesson.full")

        price(staff_client, "lesson.full", credits=now)

        assert ActionPrice.objects.filter(key="lesson.full").count() == 1 and not AuditEntry.objects.exists()

    def test_zero_is_a_price(self, staff_client):
        assert price(staff_client, "lesson.full", credits=0).json()["credits"] == 0

    @pytest.mark.parametrize("credits", [-1, "free", None, 1.5])
    def test_a_price_that_is_not_a_whole_number_of_credits_is_refused(self, staff_client, credits):
        response = price(staff_client, "lesson.full", credits=credits)

        assert response.status_code == 400 and "credits" in response.json()["fields"]
        assert not AuditEntry.objects.exists()

    def test_an_unknown_key_is_a_404_and_makes_no_price(self, staff_client):
        assert price(staff_client, "no.such.price", credits=3).status_code == 404
        assert not ActionPrice.objects.filter(key="no.such.price").exists()

    def test_a_key_switched_off_reads_as_unavailable_not_free(self, staff_client):
        ActionPrice.objects.filter(key="lesson.full").update(active=False)

        row = next(p for p in staff_client.get(URL).json()["prices"] if p["key"] == "lesson.full")

        assert row["available"] is False and row["credits"] is None

    def test_a_label_over_the_limit_is_refused(self, staff_client):
        assert price(staff_client, "lesson.full", credits=3, label="x" * 121).status_code == 400


class TestPlans:
    def test_an_edit_changes_what_was_sent_and_is_logged(self, staff_client, staff_user):
        response = staff_client.patch(f"{URL}/plans/weekly_pro", {"credits": 120, "active": False}, format="json")

        body = response.json()
        assert response.status_code == 200 and (body["credits"], body["active"]) == (120, False)
        plan = Plan.objects.get(key="weekly_pro")
        assert (plan.credits, plan.active, plan.price_paise) == (120, False, body["price_paise"])
        entry = AuditEntry.objects.get(action="credits.plan")
        assert (entry.target_id, entry.before["credits"], entry.after["credits"]) == ("weekly_pro", 100, 120)

    def test_a_value_the_model_refuses_changes_nothing(self, staff_client):
        response = staff_client.patch(f"{URL}/plans/weekly_pro", {"credits": -5}, format="json")

        assert response.status_code == 400
        assert Plan.objects.get(key="weekly_pro").credits == 100 and not AuditEntry.objects.exists()

    def test_an_unknown_plan_is_a_404_and_the_key_cannot_be_changed(self, staff_client):
        assert staff_client.patch(f"{URL}/plans/nothing", {"credits": 1}, format="json").status_code == 404

        staff_client.patch(f"{URL}/plans/weekly_pro", {"key": "pro_plus"}, format="json")

        assert Plan.objects.get(key="weekly_pro").key == "weekly_pro"

    def test_what_was_already_bought_is_not_changed(self, staff_client, user):
        plan = Plan.objects.get(key="weekly_pro")
        purchase = PlanPurchase.objects.create(
            user=user,
            plan=plan,
            quantity=1,
            amount_paise=plan.price_paise,
            created_at=timezone.now(),
        )

        staff_client.patch(f"{URL}/plans/weekly_pro", {"price_paise": 999}, format="json")

        purchase.refresh_from_db()
        assert purchase.amount_paise != 999

    def test_an_edit_that_changes_nothing_writes_nothing(self, staff_client):
        staff_client.patch(f"{URL}/plans/weekly_pro", {"credits": 100}, format="json")

        assert not AuditEntry.objects.exists()


class TestSettings:
    def test_an_edit_is_validated_saved_and_logged(self, staff_client, staff_user):
        response = staff_client.patch(f"{URL}/settings", {"signup_credits": 40, "daily_credits": 2}, format="json")

        assert response.status_code == 200 and response.json()["signup_credits"] == 40
        saved = CreditSettings.load()
        assert (saved.signup_credits, saved.daily_credits) == (40, 2)
        entry = AuditEntry.objects.get(action="credits.settings")
        assert (entry.before["signup_credits"], entry.after["signup_credits"]) == (30, 40)

    def test_one_refused_value_saves_nothing(self, staff_client):
        response = staff_client.patch(
            f"{URL}/settings", {"signup_credits": 99, "min_one_time_credits": 0}, format="json"
        )

        assert response.status_code == 400 and "min_one_time_credits" in response.json()["fields"]
        assert CreditSettings.load().signup_credits == 30 and not AuditEntry.objects.exists()

    def test_the_retired_setting_is_not_accepted(self, staff_client):
        staff_client.patch(f"{URL}/settings", {"paise_per_credit": 5}, format="json")

        assert not hasattr(CreditSettings.load(), "paise_per_credit") and not AuditEntry.objects.exists()
