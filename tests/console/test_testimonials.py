"""Unit under test: `/api/console/testimonials` and its writes (`console.services.testimonials.TestimonialDesk`): the
console screen that decides which learners' words the landing page shows.

Why: a testimonial on the front page is a promise to the person quoted and to every visitor. So the console must make it
hard to break either: nothing is published without the learner's consent confirmed, a sample (a placeholder made for a
developer's machine) can never be published from here, every change is written to the change log with what it was and
what it became, and only staff can reach any of it. The public page reads the same rows, so a change here must show
there at once.

Use cases:
- staff read every testimonial, published or not, samples included, in position order, with everything the screen shows
- adding one puts it last, unpublished unless asked, never a sample, and writes `testimonial.create` with its fields
- adding one that is published needs consent confirmed; a blank name, context or quote, a quote over 300 characters
  and a rating outside 1 to 5 are refused with the field named and nothing saved
- editing changes only what was sent, is checked by the model's rules and writes `testimonial.update` with before and
  after; an edit that changes nothing writes nothing; a sample flag cannot be changed from the console
- publishing and unpublishing are edits of `is_published`: publishing without consent, or a sample, is refused with a
  clear message; taking consent away from a published one is refused until it is unpublished
- a published testimonial shows on the public endpoint at once, and an unpublished or deleted one is gone from it
- deleting removes it, writes `testimonial.delete` with what it was, and a missing one is a 404
- reordering takes every id in the new order, renumbers the positions, writes one `testimonial.reorder` and changes the
  public order; a list that misses an id, repeats one or names a stranger is refused; the same order writes nothing
- anyone not signed in and any learner get a 404 on every path and nothing changes; a write without the CSRF header is a
  403
- the screen is read in a fixed number of queries
"""

import pytest
from rest_framework.test import APIClient

from console.models import AuditEntry
from marketing.models import Testimonial

pytestmark = pytest.mark.django_db

URL = "/api/console/testimonials"
GOOD = {"name": "Asha Rao", "context": "Class 12 student", "quote": "It skipped what I already knew.", "rating": 5}


def make(**fields) -> Testimonial:
    values = {
        "name": "Asha Rao",
        "context": "Class 12 student",
        "quote": "Skipped what I knew.",
        "position": 1,
        **fields,
    }
    return Testimonial.objects.create(**values)


def public_names(client) -> list[str]:
    return [t["name"] for t in client.get("/api/public/testimonials").json()["testimonials"]]


class TestReading:
    def test_staff_see_every_testimonial_in_position_order_with_all_its_fields(self, staff_client):
        make(name="Second", position=2)
        make(name="Sample", position=1, is_sample=True)

        body = staff_client.get(URL).json()

        assert [t["name"] for t in body["testimonials"]] == ["Sample", "Second"]
        assert set(body["testimonials"][0]) == {
            "id", "name", "context", "quote", "rating", "position", "is_published", "consent_confirmed", "is_sample",
            "created_at", "updated_at",
        }  # fmt: skip
        assert body["testimonials"][0]["is_sample"] is True

    def test_the_screen_is_read_in_a_fixed_number_of_queries(self, staff_client, count_queries):
        make()
        few = count_queries(lambda: staff_client.get(URL))
        for index in range(5):
            make(name=f"N{index}", position=index + 2)

        assert count_queries(lambda: staff_client.get(URL)) == few


class TestAdding:
    def test_a_new_one_goes_last_unpublished_and_is_never_a_sample(self, staff_client, staff_user):
        make(position=4)

        response = staff_client.post(URL, GOOD, format="json")

        assert response.status_code == 201
        body = response.json()
        assert (body["position"], body["is_published"], body["is_sample"], body["consent_confirmed"]) == (
            5,
            False,
            False,
            False,
        )
        entry = AuditEntry.objects.get()
        assert (entry.action, entry.target_type, entry.target_id, entry.actor_id) == (
            "testimonial.create", "testimonial", str(body["id"]), staff_user.id
        )  # fmt: skip
        assert entry.before is None and entry.after["name"] == "Asha Rao" and entry.after["is_published"] is False

    def test_it_can_be_added_already_published_when_consent_is_confirmed(self, staff_client, api_client):
        response = staff_client.post(URL, {**GOOD, "consent_confirmed": True, "is_published": True}, format="json")

        assert response.status_code == 201 and public_names(api_client) == ["Asha Rao"]

    def test_a_sample_flag_in_the_request_is_ignored(self, staff_client):
        body = staff_client.post(URL, {**GOOD, "is_sample": True}, format="json").json()

        assert body["is_sample"] is False

    @pytest.mark.parametrize(
        ("change", "field"),
        [
            ({"name": "  "}, "name"),
            ({"context": ""}, "context"),
            ({"quote": " "}, "quote"),
            ({"quote": "q" * 301}, "quote"),
            ({"rating": 0}, "rating"),
            ({"rating": 6}, "rating"),
            ({"is_published": True}, "is_published"),
        ],
    )
    def test_a_bad_one_is_refused_naming_the_field_and_nothing_is_saved(self, staff_client, change, field):
        response = staff_client.post(URL, {**GOOD, **change}, format="json")

        assert response.status_code == 400 and field in response.json()["fields"]
        assert not Testimonial.objects.exists() and not AuditEntry.objects.exists()

    def test_the_rating_may_be_left_out(self, staff_client):
        body = {k: v for k, v in GOOD.items() if k != "rating"}

        response = staff_client.post(URL, body, format="json")

        assert response.status_code == 201 and response.json()["rating"] is None


class TestEditing:
    def test_only_what_was_sent_changes_and_the_log_has_before_and_after(self, staff_client, staff_user):
        row = make()

        response = staff_client.patch(f"{URL}/{row.pk}", {"quote": "A better quote.", "rating": 4}, format="json")

        row.refresh_from_db()
        assert response.status_code == 200 and (row.quote, row.rating, row.name) == ("A better quote.", 4, "Asha Rao")
        entry = AuditEntry.objects.get()
        assert (entry.action, entry.target_type, entry.target_id) == ("testimonial.update", "testimonial", str(row.pk))
        assert entry.before["quote"] == "Skipped what I knew." and entry.after["quote"] == "A better quote."
        assert entry.before["rating"] is None and entry.after["rating"] == 4

    def test_an_edit_that_changes_nothing_writes_nothing(self, staff_client):
        row = make()

        response = staff_client.patch(f"{URL}/{row.pk}", {"name": row.name}, format="json")

        assert response.status_code == 200 and not AuditEntry.objects.exists()

    def test_a_refused_edit_changes_nothing_and_writes_nothing(self, staff_client):
        row = make()

        response = staff_client.patch(f"{URL}/{row.pk}", {"quote": "q" * 400, "name": "New"}, format="json")

        row.refresh_from_db()
        assert response.status_code == 400 and row.name == "Asha Rao" and not AuditEntry.objects.exists()

    def test_the_sample_flag_cannot_be_changed_here(self, staff_client):
        row = make(is_sample=True)

        staff_client.patch(f"{URL}/{row.pk}", {"is_sample": False}, format="json")

        row.refresh_from_db()
        assert row.is_sample is True

    def test_a_missing_one_is_a_404(self, staff_client):
        assert staff_client.patch(f"{URL}/999999", {"name": "x"}, format="json").status_code == 404


class TestPublishing:
    def test_publishing_with_consent_shows_it_on_the_public_page_at_once(self, staff_client, api_client):
        row = make(consent_confirmed=True)
        assert public_names(api_client) == []

        response = staff_client.patch(f"{URL}/{row.pk}", {"is_published": True}, format="json")

        assert response.status_code == 200 and public_names(api_client) == ["Asha Rao"]
        assert AuditEntry.objects.get().after["is_published"] is True

    def test_publishing_and_consent_can_be_sent_together(self, staff_client):
        row = make()

        response = staff_client.patch(
            f"{URL}/{row.pk}", {"consent_confirmed": True, "is_published": True}, format="json"
        )

        assert response.status_code == 200 and response.json()["is_published"] is True

    def test_publishing_without_consent_is_refused_with_a_clear_message(self, staff_client, api_client):
        row = make()

        response = staff_client.patch(f"{URL}/{row.pk}", {"is_published": True}, format="json")

        message = response.json()["fields"]["is_published"][0]
        assert response.status_code == 400 and "consent" in message.lower()
        assert public_names(api_client) == [] and not AuditEntry.objects.exists()

    def test_a_sample_cannot_be_published_even_with_consent(self, staff_client, api_client):
        row = make(is_sample=True)

        response = staff_client.patch(
            f"{URL}/{row.pk}", {"consent_confirmed": True, "is_published": True}, format="json"
        )

        message = response.json()["fields"]["is_published"][0]
        assert response.status_code == 400 and "sample" in message.lower() and public_names(api_client) == []

    def test_unpublishing_takes_it_off_the_public_page(self, staff_client, api_client):
        row = make(consent_confirmed=True, is_published=True)
        assert public_names(api_client) == ["Asha Rao"]

        staff_client.patch(f"{URL}/{row.pk}", {"is_published": False}, format="json")

        assert public_names(api_client) == []

    def test_consent_cannot_be_taken_away_while_it_is_published(self, staff_client):
        row = make(consent_confirmed=True, is_published=True)

        response = staff_client.patch(f"{URL}/{row.pk}", {"consent_confirmed": False}, format="json")

        row.refresh_from_db()
        assert response.status_code == 400 and row.consent_confirmed is True

    def test_consent_can_be_taken_away_in_the_same_edit_that_unpublishes(self, staff_client):
        row = make(consent_confirmed=True, is_published=True)

        response = staff_client.patch(
            f"{URL}/{row.pk}", {"consent_confirmed": False, "is_published": False}, format="json"
        )

        assert response.status_code == 200


class TestDeleting:
    def test_it_removes_the_row_and_writes_what_it_was(self, staff_client, api_client):
        row = make(consent_confirmed=True, is_published=True)

        response = staff_client.delete(f"{URL}/{row.pk}")

        assert response.status_code == 204 and not Testimonial.objects.exists() and public_names(api_client) == []
        entry = AuditEntry.objects.get()
        assert (entry.action, entry.target_id) == ("testimonial.delete", str(row.pk))
        assert entry.before["name"] == "Asha Rao" and entry.after is None

    def test_a_missing_one_is_a_404_and_writes_nothing(self, staff_client):
        assert staff_client.delete(f"{URL}/999999").status_code == 404
        assert not AuditEntry.objects.exists()


class TestReordering:
    def three(self):
        return [
            make(name=n, position=i, consent_confirmed=True, is_published=True)
            for i, n in ((1, "A"), (2, "B"), (3, "C"))
        ]

    def test_the_new_order_renumbers_the_positions_and_changes_the_public_order(self, staff_client, api_client):
        a, b, c = self.three()

        response = staff_client.post(f"{URL}/reorder", {"ids": [c.pk, a.pk, b.pk]}, format="json")

        assert response.status_code == 200
        assert [t["name"] for t in response.json()["testimonials"]] == ["C", "A", "B"]
        assert [t.position for t in Testimonial.objects.all()] == [1, 2, 3]
        assert public_names(api_client) == ["C", "A", "B"]
        entry = AuditEntry.objects.get()
        assert entry.action == "testimonial.reorder"
        assert entry.before == {"order": [a.pk, b.pk, c.pk]} and entry.after == {"order": [c.pk, a.pk, b.pk]}

    def test_the_same_order_writes_nothing(self, staff_client):
        a, b, c = self.three()

        response = staff_client.post(f"{URL}/reorder", {"ids": [a.pk, b.pk, c.pk]}, format="json")

        assert response.status_code == 200 and not AuditEntry.objects.exists()

    @pytest.mark.parametrize("bad", ["missing", "repeated", "stranger", "not a list"])
    def test_a_list_that_is_not_every_id_once_is_refused(self, staff_client, bad):
        a, b, c = self.three()
        ids = {"missing": [a.pk, b.pk], "repeated": [a.pk, a.pk, b.pk, c.pk], "stranger": [a.pk, b.pk, c.pk, 999999],
               "not a list": "abc"}[bad]  # fmt: skip

        response = staff_client.post(f"{URL}/reorder", {"ids": ids}, format="json")

        assert response.status_code == 400
        assert [t.position for t in Testimonial.objects.all()] == [1, 2, 3] and not AuditEntry.objects.exists()


class TestWhoMayUseIt:
    def paths(self):
        row = make()
        return [
            ("get", URL, None), ("post", URL, GOOD), ("patch", f"{URL}/{row.pk}", {"name": "x"}),
            ("delete", f"{URL}/{row.pk}", None), ("post", f"{URL}/reorder", {"ids": [row.pk]}),
        ]  # fmt: skip

    def test_anyone_not_signed_in_and_any_learner_get_a_404_and_nothing_changes(self, api_client, learner_client):
        paths = self.paths()
        for client in (api_client, learner_client):
            for method, path, body in paths:
                response = getattr(client, method)(path, body, format="json")
                assert response.status_code == 404, (method, path)

        row = Testimonial.objects.get()
        assert (row.name, row.position) == ("Asha Rao", 1) and not AuditEntry.objects.exists()

    def test_a_write_needs_the_csrf_header_as_well_as_the_session_cookie(self, staff_user):
        client = APIClient(enforce_csrf_checks=True)
        client.get("/api/auth/csrf")
        token = client.cookies["csrftoken"].value
        client.post("/api/auth/login", {"email": staff_user.email, "password": "correct-horse-battery-staple"},
                    format="json", HTTP_X_CSRFTOKEN=token)  # fmt: skip

        without = client.post(URL, GOOD, format="json")
        with_token = client.post(URL, GOOD, format="json", HTTP_X_CSRFTOKEN=token)

        assert without.status_code == 403 and with_token.status_code == 201
        assert Testimonial.objects.count() == 1

    def test_responses_are_never_cached(self, staff_client):
        assert staff_client.get(URL)["Cache-Control"] == "no-store"
