"""Unit under test: `credits.pricing.book` (`PriceBook`, `PriceCatalog`), `credits.pricing.seed.PriceSeed`, the
`ActionPrice` model, and migration 0004 that seeds the prices.

Why: "prices live in the database, not the code". A price that is missing must never read as free, an edit must never
change work already in flight, and history must say what a price was. The book is read on every action, so it is cached;
an edit has to show at once everywhere, not when the cache happens to expire.

Use cases:
- the book gives the credits and label of the active row of a key; a key with no active row is unavailable (503
  `price_unavailable`), also when only an inactive row exists, and a price of 0 is a price
- the book is cached (a second read does not query) and the cache is cleared when a price is saved or deleted or revised
- only one row of a key can be active, the database insists; inactive rows can be many
- revising a price adds a row, deactivates the old one, keeps the history, records who and when, clears the cache, and
  changes nothing when the price and label are the same
- revising a key that has no price makes the first one; a negative price is refused
- the seed adds the plan's prices and only the missing ones, never changing one an administrator edited, and is
  repeatable
- migration 0004 seeds the same prices as `PriceSeed` and can be undone
"""

import importlib
from datetime import UTC, datetime, timedelta

import pytest
from django.core.cache import cache
from django.db import IntegrityError, connection, transaction
from django.test.utils import CaptureQueriesContext

from credits.models import ActionPrice
from credits.pricing.book import PriceBook, PriceCatalog
from credits.pricing.seed import PriceSeed
from credits.refusals import PriceUnavailable

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def seeded(db):
    PriceSeed().apply()
    PriceBook.clear()


class TestReading:
    def test_it_gives_the_credits_and_label_of_the_active_row(self):
        line = PriceBook().line("lesson.rest")

        assert (line.key, line.credits, line.label) == ("lesson.rest", 7, "Your lesson, after the Quick check")
        assert PriceBook().credits("lesson.rest") == 7

    def test_a_key_with_no_row_is_unavailable_not_free(self):
        with pytest.raises(PriceUnavailable) as refused:
            PriceBook().credits("lesson.imaginary")

        assert refused.value.status_code == 503 and refused.value.get_codes() == "price_unavailable"

    def test_a_key_with_only_an_inactive_row_is_unavailable(self):
        ActionPrice.objects.filter(key="lesson.rest").update(active=False)
        PriceBook.clear()

        with pytest.raises(PriceUnavailable):
            PriceBook().credits("lesson.rest")

    def test_a_price_of_zero_is_a_price(self):
        assert PriceBook().credits("sheets.after_check_single") == 0


class TestTheCache:
    def test_a_second_read_does_not_query(self):
        book = PriceBook()
        book.credits("lesson.rest")

        with CaptureQueriesContext(connection) as queries:
            book.credits("lesson.full")
            PriceBook().credits("followup.advanced")

        assert len(queries) == 0

    def test_saving_a_price_clears_it(self):
        assert PriceBook().credits("lesson.rest") == 7

        row = ActionPrice.objects.get(key="lesson.rest", active=True)
        row.credits = 11
        row.save()

        assert PriceBook().credits("lesson.rest") == 11

    def test_deleting_a_price_clears_it(self):
        PriceBook().credits("lesson.rest")

        ActionPrice.objects.get(key="lesson.rest", active=True).delete()

        with pytest.raises(PriceUnavailable):
            PriceBook().credits("lesson.rest")

    def test_clear_forgets_what_was_read(self):
        PriceBook().credits("lesson.rest")
        assert cache.get(PriceBook.CACHE_KEY) is not None

        PriceBook.clear()

        assert cache.get(PriceBook.CACHE_KEY) is None


class TestOneActiveRow:
    def test_the_database_allows_one_active_row_for_a_key(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            ActionPrice.objects.create(key="lesson.rest", credits=1, label="x", active=True, updated_at=NOW)

    def test_inactive_rows_may_be_many(self):
        for n in range(3):
            ActionPrice.objects.create(key="lesson.rest", credits=n, label="old", active=False, updated_at=NOW)

        assert ActionPrice.objects.filter(key="lesson.rest").count() == 4


class TestRevising:
    def test_it_adds_a_row_deactivates_the_old_one_and_keeps_the_history(self):
        old = ActionPrice.objects.get(key="lesson.rest", active=True)

        made = PriceCatalog().revise("lesson.rest", 8, by="staff@example.com", now=NOW)

        old.refresh_from_db()
        assert old.active is False and old.credits == 7
        assert (made.credits, made.active, made.updated_by, made.updated_at) == (8, True, "staff@example.com", NOW)
        assert made.label == old.label and made.pk != old.pk
        assert PriceBook().credits("lesson.rest") == 8
        assert list(ActionPrice.objects.filter(key="lesson.rest").order_by("id").values_list("credits", "active")) == [
            (7, False),
            (8, True),
        ]

    def test_a_new_label_is_kept(self):
        made = PriceCatalog().revise("lesson.rest", 7, by="staff", now=NOW, label="The rest of your lesson")

        assert made.label == "The rest of your lesson" and PriceBook().line("lesson.rest").label == made.label

    def test_nothing_changes_when_the_price_and_label_are_the_same(self):
        before = ActionPrice.objects.count()

        same = PriceCatalog().revise("lesson.rest", 7, by="staff", now=NOW)

        assert ActionPrice.objects.count() == before and same.active is True and same.updated_by != "staff"

    def test_a_key_with_no_price_gets_its_first(self):
        made = PriceCatalog().revise("lesson.brand_new", 4, by="staff", now=NOW, label="Brand new")

        assert PriceBook().credits("lesson.brand_new") == 4 and made.label == "Brand new"

    def test_a_negative_price_is_refused_and_the_old_one_stays(self):
        with pytest.raises(ValueError):
            PriceCatalog().revise("lesson.rest", -1, by="staff", now=NOW)

        assert PriceBook().credits("lesson.rest") == 7

    def test_it_can_switch_a_price_off(self):
        PriceCatalog().deactivate("lesson.rest", by="staff", now=NOW)

        with pytest.raises(PriceUnavailable):
            PriceBook().credits("lesson.rest")
        assert ActionPrice.objects.filter(key="lesson.rest", active=False).count() == 1


class TestTheSeed:
    def test_it_adds_the_plans_prices(self):
        ActionPrice.objects.all().delete()

        added = PriceSeed().apply()

        assert added == len(PriceSeed.PRICES) == 18
        assert {p.key: p.credits for p in ActionPrice.objects.filter(active=True)} == PriceSeed.PRICES
        assert all(p.label for p in ActionPrice.objects.all())

    def test_it_adds_only_what_is_missing_and_never_overwrites_an_edit(self):
        PriceCatalog().revise("lesson.rest", 8, by="staff", now=NOW)
        ActionPrice.objects.filter(key="lesson.full").delete()

        added = PriceSeed().apply()

        assert added == 1
        assert PriceBook().credits("lesson.rest") == 8 and PriceBook().credits("lesson.full") == 10

    def test_it_is_repeatable(self):
        assert PriceSeed().apply() == 0


class TestTheMigration:
    def migration(self):
        return importlib.import_module("credits.migrations.0004_price_seed")

    def test_it_seeds_the_prices_the_seed_class_holds(self):
        ActionPrice.objects.all().delete()
        from django.apps import apps

        self.migration().seed(apps, None)

        assert {p.key: (p.credits, p.active) for p in ActionPrice.objects.all()} == {
            key: (credits, True) for key, credits in PriceSeed.PRICES.items()
        }

    def test_it_never_overwrites_a_price_that_is_already_there(self):
        from django.apps import apps

        PriceCatalog().revise("lesson.rest", 8, by="staff", now=NOW + timedelta(days=1))

        self.migration().seed(apps, None)

        assert PriceBook().credits("lesson.rest") == 8

    def test_undoing_it_removes_only_the_seeded_prices(self):
        from django.apps import apps

        ActionPrice.objects.create(key="custom.thing", credits=1, label="Custom", active=True, updated_at=NOW)

        self.migration().unseed(apps, None)

        assert list(ActionPrice.objects.values_list("key", flat=True)) == ["custom.thing"]
