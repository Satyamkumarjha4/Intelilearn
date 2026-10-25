"""Unit under test: `console.services.flow_settings.FlowSettingsService` behind `GET` and `PATCH
/api/console/flow-settings`.

Why: these settings decide how long the quick check is, who is sent to the foundations, how hard the quality checks
push. They have to be editable with the admin's own rules (not looser, or a typo breaks every new lesson), and the
screen needs the consequence of them in numbers: where a score sends a learner.

Use cases:
- the settings are read with the thresholds they imply: questions in the quick check, the last score sent to the
  foundations, the lowest score that can be mastery
- a change is saved, the thresholds follow it, and one audit entry keeps the settings before and after
- the rules are exactly the admin form's: whatever the form refuses is refused here, whatever it accepts is accepted
- a field that does not exist, or a wrong type, is refused; a refused change saves nothing and logs nothing
- lessons already started keep the settings they started with
- none of it is open to a learner
"""

import pytest
from django.forms import modelform_factory

from console.models import AuditEntry
from lessons.models import FlowSettings

pytestmark = pytest.mark.django_db

URL = "/api/console/flow-settings"
AdminForm = modelform_factory(FlowSettings, fields="__all__")  # what the Django admin builds for this model

FIELDS = {
    "diagnostic_questions_per_band", "prerequisite_question_count", "prereq_trigger_max_correct",
    "mastery_requires_all_correct", "final_test_min", "final_test_max", "max_interactives_per_page",
    "alignment_min_score", "alignment_max_rounds", "render_check_max_rounds", "max_auto_runtime_repairs",
    "media_sources", "allowed_media_licenses",
}  # fmt: skip


def test_the_settings_come_with_the_thresholds_they_imply(staff_client):
    body = staff_client.get(URL).json()

    assert set(body) == FIELDS | {"routing_thresholds"}
    assert body["diagnostic_questions_per_band"] == 2 and body["media_sources"] == ["wikimedia", "openverse"]
    assert body["routing_thresholds"] == {"questions_total": 10, "foundations_max": 2, "mastery_min": 10}


def test_reading_the_settings_creates_the_single_row_if_there_is_none(staff_client):
    assert not FlowSettings.objects.exists()

    staff_client.get(URL)

    assert FlowSettings.objects.count() == 1


def test_a_change_is_saved_and_the_thresholds_follow_it(staff_client, staff_user):
    response = staff_client.patch(
        URL,
        {
            "diagnostic_questions_per_band": 3,
            "prereq_trigger_max_correct": 4,
            "mastery_requires_all_correct": False,
            "media_sources": ["wikimedia", "giphy"],
        },
        format="json",  # fmt: skip
    )

    assert response.status_code == 200
    saved = FlowSettings.load()
    assert saved.diagnostic_questions_per_band == 3 and saved.prereq_trigger_max_correct == 4
    assert saved.mastery_requires_all_correct is False
    assert saved.media_sources == ["wikimedia", "giphy"] and saved.final_test_max == 15  # the rest is as it was
    assert response.json()["routing_thresholds"] == {"questions_total": 15, "foundations_max": 4, "mastery_min": 14}
    assert response.json() == staff_client.get(URL).json()
    [entry] = AuditEntry.objects.all()
    assert (entry.actor_id, entry.action, entry.target_type, entry.target_id) == (staff_user.id,
                                                                                   "flow_settings.update",
                                                                                   "flow_settings", "1")  # fmt: skip
    assert entry.before["diagnostic_questions_per_band"] == 2 and entry.after["diagnostic_questions_per_band"] == 3
    assert "routing_thresholds" not in entry.after


def test_an_empty_change_is_accepted_and_changes_nothing(staff_client):
    before = FlowSettings.load().snapshot()

    assert staff_client.patch(URL, {}, format="json").status_code == 200
    assert FlowSettings.load().snapshot() == before


BAD = [
    {"diagnostic_questions_per_band": 0},  # at least 1
    {"diagnostic_questions_per_band": 5},  # at most 4
    {"prerequisite_question_count": 11},
    {"prerequisite_question_count": 0},
    {"alignment_min_score": 6},
    {"alignment_min_score": 0},
    {"final_test_min": -1},
    {"max_interactives_per_page": 100_000},  # beyond a small integer column
    {"prereq_trigger_max_correct": "many"},
    {"media_sources": []},  # the form wants at least one source
]
GOOD = [
    {"diagnostic_questions_per_band": 4},
    {"prerequisite_question_count": 10},
    {"alignment_min_score": 5},
    {"final_test_min": 20, "final_test_max": 5},  # the admin does not compare the two, and nor do we
    {"media_sources": ["giphy"], "allowed_media_licenses": ["cc0"]},
    {"mastery_requires_all_correct": False},
]


def admin_accepts(changes):
    return AdminForm({**FlowSettings.load().snapshot(), **changes}, instance=FlowSettings.load()).is_valid()


@pytest.mark.parametrize("changes", BAD)
def test_what_the_admin_form_refuses_is_refused(staff_client, changes):
    assert admin_accepts(changes) is False  # the premise: the admin refuses it
    before = FlowSettings.load().snapshot()

    response = staff_client.patch(URL, changes, format="json")

    assert response.status_code == 400 and set(response.json()["fields"]) == set(changes)
    assert FlowSettings.load().snapshot() == before and not AuditEntry.objects.exists()


@pytest.mark.parametrize("changes", GOOD)
def test_what_the_admin_form_accepts_is_accepted(staff_client, changes):
    assert admin_accepts(changes) is True

    response = staff_client.patch(URL, changes, format="json")

    assert response.status_code == 200
    for field, value in changes.items():
        assert response.json()[field] == value


def test_a_value_of_the_wrong_type_is_refused_even_where_the_form_would_let_it_through(staff_client):
    # an HTML checkbox turns any text into a yes; an API client that sends "maybe" has made a mistake
    response = staff_client.patch(URL, {"mastery_requires_all_correct": "maybe"}, format="json")

    assert response.status_code == 400 and "mastery_requires_all_correct" in response.json()["fields"]


def test_one_bad_value_saves_none_of_the_good_ones_sent_with_it(staff_client):
    response = staff_client.patch(URL, {"final_test_max": 20, "alignment_min_score": 9}, format="json")

    assert response.status_code == 400
    assert FlowSettings.load().final_test_max == 15


@pytest.mark.parametrize("field", ["id", "pk", "routing_thresholds", "nonsense"])
def test_a_field_that_cannot_be_set_is_refused(staff_client, field):
    response = staff_client.patch(URL, {field: 1}, format="json")

    assert response.status_code == 400 and field in response.json()["fields"]


def test_lessons_already_started_keep_the_settings_they_started_with(staff_client, lesson):
    from lessons.models import Lesson

    Lesson.objects.filter(pk=lesson.pk).update(settings_snapshot=FlowSettings.load().snapshot())

    staff_client.patch(URL, {"diagnostic_questions_per_band": 4}, format="json")

    assert Lesson.objects.get(pk=lesson.pk).settings_snapshot["diagnostic_questions_per_band"] == 2
    assert FlowSettings.load().diagnostic_questions_per_band == 4


def test_a_learner_can_neither_read_nor_change_the_settings(learner_client):
    assert learner_client.get(URL).status_code == 404
    assert learner_client.patch(URL, {"final_test_min": 1}, format="json").status_code == 404
