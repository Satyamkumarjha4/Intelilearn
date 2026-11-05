"""Unit under test: the `ActionPrice` screens of the Django admin (`credits.admin.ActionPriceAdmin`).

Why: prices live in the database so an operator can change them without a deploy. A price edited in place would rewrite
history and change work already in flight, so an edit must add a row and switch the old one off; and a key must never
end
up with two live prices, or with none by accident.

Use cases:
- the changelist renders and shows the live and the old prices
- a price for a new key can be added and is live at once; a second live price for a key is refused
- editing a live price adds a row and switches the old one off, with the administrator's email and the time on the new
  one; the key cannot be changed; the quote follows at once (the cache is cleared)
- editing only the label also adds a row; saving with nothing changed adds nothing
- an old price cannot be revived by editing it, a price cannot be deleted, and switching a price off makes the key
  unavailable (503) rather than free
"""

import pytest
from django.urls import reverse

from credits.models import ActionPrice
from credits.pricing.book import PriceBook
from credits.pricing.seed import PriceSeed
from credits.refusals import PriceUnavailable

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def prices(db):
    PriceSeed().apply()
    PriceBook.clear()


def live(key) -> ActionPrice:
    return ActionPrice.objects.get(key=key, active=True)


def change_url(row):
    return reverse("admin:credits_actionprice_change", args=[row.pk])


def test_the_changelist_renders(admin_client):
    assert admin_client.get(reverse("admin:credits_actionprice_changelist")).status_code == 200


def test_a_price_for_a_new_key_is_added_live(admin_client):
    response = admin_client.post(
        reverse("admin:credits_actionprice_add"),
        {"key": "lesson.new_thing", "credits": 4, "label": "A new thing", "active": "on"},
    )

    assert response.status_code == 302
    made = live("lesson.new_thing")
    assert (made.credits, made.updated_by) == (4, "admin@example.com") and made.updated_at is not None
    assert PriceBook().credits("lesson.new_thing") == 4


def test_a_second_live_price_for_a_key_is_refused(admin_client):
    response = admin_client.post(
        reverse("admin:credits_actionprice_add"), {"key": "lesson.rest", "credits": 1, "label": "x", "active": "on"}
    )

    assert response.status_code == 200 and ActionPrice.objects.filter(key="lesson.rest").count() == 1


def test_editing_a_live_price_adds_a_row_and_switches_the_old_one_off(admin_client):
    old = live("lesson.rest")

    response = admin_client.post(
        change_url(old), {"key": "lesson.rest", "credits": 9, "label": old.label, "active": "on"}
    )

    assert response.status_code == 302
    old.refresh_from_db()
    new = live("lesson.rest")
    assert old.active is False and old.credits == 7 and new.pk != old.pk
    assert (new.credits, new.updated_by, new.label) == (9, "admin@example.com", old.label)
    assert PriceBook().credits("lesson.rest") == 9
    assert ActionPrice.objects.filter(key="lesson.rest").count() == 2


def test_the_key_cannot_be_changed_by_an_edit(admin_client):
    old = live("lesson.rest")

    admin_client.post(change_url(old), {"key": "lesson.other", "credits": 9, "label": old.label, "active": "on"})

    assert live("lesson.rest").credits == 9 and not ActionPrice.objects.filter(key="lesson.other").exists()


def test_editing_only_the_label_adds_a_row_too(admin_client):
    old = live("lesson.rest")

    admin_client.post(change_url(old), {"credits": old.credits, "label": "The rest of your lesson", "active": "on"})

    assert (
        live("lesson.rest").label == "The rest of your lesson"
        and ActionPrice.objects.filter(key="lesson.rest").count() == 2
    )


def test_saving_with_nothing_changed_adds_nothing(admin_client):
    old = live("lesson.rest")

    admin_client.post(change_url(old), {"credits": old.credits, "label": old.label, "active": "on"})

    assert ActionPrice.objects.filter(key="lesson.rest").count() == 1 and live("lesson.rest").pk == old.pk


def test_switching_a_price_off_makes_the_key_unavailable_not_free(admin_client):
    old = live("lesson.rest")

    admin_client.post(change_url(old), {"credits": old.credits, "label": old.label})  # `active` left unticked

    with pytest.raises(PriceUnavailable):
        PriceBook().credits("lesson.rest")
    assert ActionPrice.objects.filter(key="lesson.rest", active=False).count() == 1


def test_an_old_price_cannot_be_revived_by_editing_it(admin_client):
    old = live("lesson.rest")
    admin_client.post(change_url(old), {"credits": 9, "label": old.label, "active": "on"})
    old.refresh_from_db()

    admin_client.post(change_url(old), {"credits": 7, "label": old.label, "active": "on"})

    assert live("lesson.rest").credits == 9 and ActionPrice.objects.filter(key="lesson.rest").count() == 2


def test_a_price_cannot_be_deleted(admin_client):
    row = live("lesson.rest")

    assert (
        admin_client.post(reverse("admin:credits_actionprice_delete", args=[row.pk]), {"post": "yes"}).status_code
        == 403
    )
    assert ActionPrice.objects.filter(pk=row.pk).exists()
