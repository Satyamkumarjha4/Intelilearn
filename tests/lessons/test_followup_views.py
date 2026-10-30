"""Unit under test: the follow-up endpoint (`POST /api/lessons/{id}/followups`) and the fields that link a lesson to its
follow-ups (`GET /api/lessons/{id}`, `GET /api/lessons`), as the browser uses them.

Why: this is the button behind "Make a Foundation lesson". A double click must make one lesson, another learner's lesson
must be a 404, a lesson that exists must be handed back to be opened (not made again), and the page needs to show both
ways of the link without a second request.

Use cases:
- it needs a signed-in learner, the learner's own ready lesson, and a known level
- it answers 202 with the new lesson and its run; the new lesson is the learner's own, made from the parent, with the
  topic of its level and the follow-up's entry and origin
- asking again for a level that exists is a 409 `already_exists` that names the lesson, and the other level is allowed
- a lesson that is not ready is a 409 `wrong_stage`; another learner's lesson is a 404; an unknown or missing level is
  a 400
- the Idempotency-Key returns the first answer and asks the gate once
- it counts against the new-lesson rate limit, and a refused action creates nothing
- `POST /lessons` still refuses a client that claims `origin: followup`
- a lesson's detail names the lesson it was made from (with its kind) and its Foundation and Advanced follow-ups, as
  links
  with a title (the topic when there is no title yet) or null; a follow-up whose parent was deleted has no link
- the list says how each lesson was started and what kind of follow-up it is
"""

import pytest
from rest_framework.throttling import SimpleRateThrottle
from support.gates import SharedCountingGate

from lessons.models import Lesson, Stage

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def gate(settings):
    SharedCountingGate.reset()
    settings.ACTION_GATE = "support.gates.SharedCountingGate"
    return SharedCountingGate


@pytest.fixture
def ready(make_lesson):
    return make_lesson(stage=Stage.READY, title="Binary search", settings_snapshot={})


def url(lesson):
    return f"/api/lessons/{lesson.id}/followups"


class TestMaking:
    def test_it_needs_a_signed_in_learner(self, api_client, ready):
        assert api_client.post(url(ready), {"level": "foundation"}, format="json").status_code in (401, 403)

    def test_it_answers_with_the_new_lesson_and_its_run(self, signed_in_client, ready, queue, bound_registry, user):
        response = signed_in_client.post(url(ready), {"level": "foundation"}, format="json")

        assert response.status_code == 202
        made = Lesson.objects.get(created_from_lesson=ready)
        assert response.json() == {"lesson_id": str(made.id), "run_id": str(queue.runs[0].id)}
        assert (made.owner, made.topic, made.entry, made.origin, made.followup_level) == (
            user, "Foundations of Binary search", "followup", "followup", "foundation",
        )  # fmt: skip

    def test_a_level_that_exists_is_handed_back_to_be_opened(self, signed_in_client, ready, queue, bound_registry):
        first = signed_in_client.post(url(ready), {"level": "advanced"}, format="json").json()["lesson_id"]

        again = signed_in_client.post(url(ready), {"level": "advanced"}, format="json")
        other = signed_in_client.post(url(ready), {"level": "foundation"}, format="json")

        assert again.status_code == 409
        assert again.json()["code"] == "already_exists" and again.json()["lesson_id"] == first
        assert other.status_code == 202 and Lesson.objects.filter(created_from_lesson=ready).count() == 2

    def test_a_lesson_that_is_not_ready_is_a_conflict(self, signed_in_client, make_lesson, bound_registry):
        building = make_lesson(stage=Stage.GENERATING_LESSON)

        response = signed_in_client.post(url(building), {"level": "foundation"}, format="json")

        assert response.status_code == 409 and response.json()["code"] == "wrong_stage"

    def test_another_learners_lesson_is_a_404(self, signed_in_client, make_lesson, other_user, bound_registry):
        theirs = make_lesson(owner=other_user, stage=Stage.READY)

        assert signed_in_client.post(url(theirs), {"level": "foundation"}, format="json").status_code == 404
        assert not Lesson.objects.filter(created_from_lesson=theirs).exists()

    @pytest.mark.parametrize(
        "body", [{}, {"level": ""}, {"level": "intermediate"}, {"level": "Foundation"}, {"level": None}]
    )
    def test_a_missing_or_unknown_level_is_a_400(self, signed_in_client, ready, bound_registry, body):
        response = signed_in_client.post(url(ready), body, format="json")

        assert response.status_code == 400 and "level" in response.json()["fields"]
        assert not Lesson.objects.filter(created_from_lesson=ready).exists()

    def test_a_lesson_id_that_is_not_an_id_is_a_404(self, signed_in_client):
        assert (
            signed_in_client.post("/api/lessons/nope/followups", {"level": "foundation"}, format="json").status_code
            == 404
        )


class TestGuards:
    def test_the_same_idempotency_key_returns_the_first_answer_and_the_gate_is_asked_once(
        self, signed_in_client, ready, queue, bound_registry, gate
    ):
        first = signed_in_client.post(url(ready), {"level": "foundation"}, format="json", HTTP_IDEMPOTENCY_KEY="k1")
        again = signed_in_client.post(url(ready), {"level": "foundation"}, format="json", HTTP_IDEMPOTENCY_KEY="k1")

        assert first.status_code == again.status_code == 202 and again.json() == first.json()
        assert again["Idempotent-Replayed"] == "true"
        assert len(gate.authorized) == 1 and len(queue.runs) == 1

    def test_it_counts_against_the_new_lesson_rate_limit(
        self, signed_in_client, ready, queue, bound_registry, monkeypatch
    ):
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "lesson_create", "2/hour")

        statuses = [
            signed_in_client.post(url(ready), {"level": level}, format="json").status_code
            for level in ("foundation", "advanced", "foundation")
        ]

        assert statuses == [202, 202, 429]

    def test_a_refused_action_creates_nothing(self, signed_in_client, ready, queue, bound_registry, settings):
        settings.ACTION_GATE = "support.gates.RefusingGate"

        response = signed_in_client.post(url(ready), {"level": "foundation"}, format="json")

        assert response.status_code == 403 and response.json()["code"] == "test_refused"
        assert not Lesson.objects.filter(created_from_lesson=ready).exists() and queue.runs == []

    def test_the_gate_is_told_it_is_a_followup_of_that_level(
        self, signed_in_client, ready, queue, bound_registry, gate
    ):
        signed_in_client.post(url(ready), {"level": "advanced"}, format="json")

        (asked,) = gate.authorized
        assert str(asked.action) == "lesson.followup" and asked.size["followup_level"] == "advanced"

    def test_a_client_cannot_claim_the_followup_origin_on_the_ordinary_route(self, signed_in_client, bound_registry):
        response = signed_in_client.post(
            "/api/lessons", {"topic": "Binary search", "origin": "followup"}, format="json"
        )

        assert response.status_code == 400 and "origin" in response.json()["fields"]


class TestTheLinks:
    def test_a_parent_lists_its_followups_as_links_and_null_for_the_levels_not_made(
        self, signed_in_client, ready, make_lesson
    ):
        base = signed_in_client.get(f"/api/lessons/{ready.id}").json()
        child = make_lesson(
            topic="Foundations of Binary search", title="", created_from_lesson=ready, followup_level="foundation"
        )

        body = signed_in_client.get(f"/api/lessons/{ready.id}").json()

        assert base["followups"] == {"foundation": None, "advanced": None} and base["followup_of"] is None
        assert body["followups"] == {
            "foundation": {"id": str(child.id), "title": "Foundations of Binary search"}, "advanced": None,
        }  # fmt: skip

    def test_a_followup_names_its_parent_and_what_kind_of_followup_it_is(self, signed_in_client, ready, make_lesson):
        child = make_lesson(created_from_lesson=ready, followup_level="advanced", topic="Advanced Binary search")

        body = signed_in_client.get(f"/api/lessons/{child.id}").json()

        assert body["followup_of"] == {"id": str(ready.id), "title": "Binary search", "level": "advanced"}
        assert (body["followup_level"], body["entry"]) == ("advanced", "diagnostic")

    def test_a_followup_whose_parent_was_deleted_has_no_link_but_keeps_its_level(
        self, signed_in_client, ready, make_lesson
    ):
        child = make_lesson(created_from_lesson=ready, followup_level="foundation")
        ready.delete()

        body = signed_in_client.get(f"/api/lessons/{child.id}").json()

        assert body["followup_of"] is None and body["followup_level"] == "foundation"

    def test_the_title_falls_back_to_the_topic_before_the_plan_has_written_one(self, signed_in_client, make_lesson):
        parent = make_lesson(stage=Stage.READY, topic="Fractions", title="")
        child = make_lesson(created_from_lesson=parent, followup_level="foundation")

        assert signed_in_client.get(f"/api/lessons/{child.id}").json()["followup_of"]["title"] == "Fractions"

    def test_the_list_says_how_a_lesson_started_and_what_kind_of_followup_it_is(
        self, signed_in_client, ready, make_lesson
    ):
        make_lesson(
            topic="Foundations of Binary search",
            entry="followup",
            created_from_lesson=ready,
            followup_level="foundation",
        )
        make_lesson(topic="Rated", entry="self_rating", self_rating_halves=4)

        rows = {r["topic"]: r for r in signed_in_client.get("/api/lessons").json()["results"]}

        row = rows["Foundations of Binary search"]
        assert (row["entry"], row["followup_level"]) == ("followup", "foundation")
        assert (rows["Rated"]["entry"], rows["Rated"]["followup_level"]) == ("self_rating", "")
        assert rows["Binary search"]["entry"] == "diagnostic"
