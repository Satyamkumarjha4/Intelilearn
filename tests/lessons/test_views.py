"""Unit under test: the lessons API views (`/api/lessons`, `/api/lessons/{id}/quizzes/...`, `/api/runs/{id}`), as the
browser uses them.

Why: this is the boundary where strangers' requests meet a learner's data. A missing ownership filter shows one learner
another's lesson; a quiz that leaks `correct_index` lets the diagnostic be passed by reading the network tab; a wrong
status code makes the UI misread a conflict as a failure.

Use cases:
- every endpoint requires a signed-in user
- listing shows only your own lessons, newest first, with search, stage filters (one stage or several, comma-separated)
  and cursor pagination, and says how the test went and how many sheets each has without a query per lesson
- starting a lesson validates the topic, queues a run, is rate limited, and reports an unconfigured registry
- starting a lesson can say how its level is found: a quick check (the default; old bodies keep working) or a rating
  from 0.5 to 5 stars in half steps, stored as halves; a rating without that entry, a missing or odd rating, an intent
  other than a lesson and an origin the server alone may set are 400s that name the field and create nothing
- a lesson says where it came from only after the server verified it: a recommendation must name the caller's own graded
  attempt and a topic it listed
- a lesson's detail says its entry, intent, origin, level source and (stars) self-rating, and whether it is only sheets
  (the list says the same, with its intent) and which sheets a sheets lesson asked for
- a lesson's detail hides the page writers' notes, reports the active run and keeps the quiz scores after a reload
- another user's lesson, quiz or run is a 404, and so is an id that is not a UUID
- deleting a lesson removes it; retrying is only for failed lessons
- the quiz has no answers; answering returns the score and route; bad, repeated or early answers get 400 and 409
- the review is available only after answering
- a run can be read, followed as an event stream (a browser's EventSource gets 200, not 406) and cancelled once
- the choice after a perfect quick check takes the Expert lesson or the sheets (or, for a lesson already waiting, one
  sheet kind), needs exactly one known choice, and is refused outside the choice
- sheets can be asked for on a new lesson (`intent: sheets` with the kinds, one or both, by quick check or rating) and
  a body that asks for none, one that is not offered, a repeat, or sheets for a lesson is a 400 naming the field
- more sheets can be requested for any ready lesson, as `kind` or `kinds`; a kind that exists is a 409 `already_exists`
  naming the kinds that exist and nothing is made; a practice sheet cannot be requested; the sheets a lesson has are
  listed with when each was made
- a sheet is served without practice solutions, which a reveal adds
- practice answers are graded on submit; another user's sheets are a 404
- the lesson detail lists its sheets
- the document is served for a ready lesson with signed media and no answers; a repair report is queued, validated and
  refused when stale, capped or early; versions are listed and one can be restored; another user's lesson is a 404
- the lesson detail reports the test's status and, once graded, its score
- the document says whether an old lesson still has its test inside the code
- the standalone test is served without answers, with its total marks and the one submission once made, and is a 409
  for a lesson that is not ready or is a mastery lesson
- the first attempt, started and handed in: it is marked at once and queued for grading when a legacy question needs a
  judge, bad answers are a 400 that leaves the attempt open, a lesson that is not ready is a 409, the attempt can be
  read with its score card (by id, or as the lesson's latest), and another user's lesson or attempt is a 404
- a failed grading is re-run on the same answers (202), and only a failed one
- the OpenAPI schema documents these endpoints
"""

import json
import uuid

import pytest
from asgiref.sync import async_to_sync
from rest_framework.throttling import SimpleRateThrottle
from support.lesson_data import make_final_test
from support.quiz_data import make_questions
from support.study_data import make_cheat_sheet, make_practice_sheet, make_revision_sheet

from lessons.models import GraphRun, Lesson, LessonVersion, Quiz, QuizAttempt, Stage, StudyMaterial, TestSubmission

pytestmark = pytest.mark.django_db

PATHS = [
    ("get", "/api/lessons"),
    ("post", "/api/lessons"),
    ("get", "/api/lessons/{lesson}"),
    ("delete", "/api/lessons/{lesson}"),
    ("post", "/api/lessons/{lesson}/retry"),
    ("get", "/api/lessons/{lesson}/quizzes/diagnostic"),
    ("post", "/api/lessons/{lesson}/quizzes/diagnostic/attempt"),
    ("get", "/api/lessons/{lesson}/quizzes/diagnostic/review"),
    ("get", "/api/runs/{run}"),
    ("get", "/api/runs/{run}/events"),
    ("post", "/api/runs/{run}/cancel"),
    ("post", "/api/lessons/{lesson}/choice"),
    ("post", "/api/lessons/{lesson}/materials"),
    ("get", "/api/lessons/{lesson}/materials"),
    ("get", "/api/lessons/{lesson}/materials/cheat_sheet"),
    ("post", "/api/lessons/{lesson}/materials/practice_sheet/grade"),
    ("get", "/api/lessons/{lesson}/document"),
    ("post", "/api/lessons/{lesson}/repair"),
    ("get", "/api/lessons/{lesson}/test"),
    ("get", "/api/lessons/{lesson}/test/submissions/{run}"),
    ("get", "/api/lessons/{lesson}/test/attempts"),
    ("post", "/api/lessons/{lesson}/test/attempts"),
    ("get", "/api/lessons/{lesson}/test/attempts/{run}"),
    ("put", "/api/lessons/{lesson}/test/attempts/{run}/answers/t1"),
    ("post", "/api/lessons/{lesson}/test/attempts/{run}/submit"),
    ("post", "/api/lessons/{lesson}/test/attempts/{run}/regrade"),
    ("get", "/api/lessons/{lesson}/test/submission"),
    ("get", "/api/lessons/{lesson}/versions"),
    ("post", "/api/lessons/{lesson}/versions/1/restore"),
]


async def collect(response) -> list[bytes]:
    """The chunks of an event stream (the view serves an async iterator)."""
    return [chunk async for chunk in response.streaming_content]


def waiting(lesson, kind="diagnostic"):
    questions = make_questions()
    quiz = Quiz.objects.create(lesson=lesson, kind=kind, questions=questions)
    Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.AWAITING_DIAGNOSTIC, settings_snapshot={})
    return quiz


def right_answers(quiz, right=5):
    return {q["id"]: q["correct_index"] if n < right else (q["correct_index"] + 1) % 4
            for n, q in enumerate(quiz.questions)}  # fmt: skip


@pytest.mark.parametrize(("method", "path"), PATHS, ids=lambda v: str(v))
def test_every_endpoint_requires_a_signed_in_user(api_client, lesson, method, path):
    run = GraphRun.objects.create(lesson=lesson, trigger=GraphRun.Trigger.START)

    response = getattr(api_client, method)(path.format(lesson=lesson.id, run=run.id))

    assert response.status_code == 401


class TestList:
    def test_shows_only_your_lessons_newest_first(self, signed_in_client, make_lesson, other_user):
        old = make_lesson(topic="Old")
        new = make_lesson(topic="New")
        make_lesson(topic="Theirs", owner=other_user)

        body = signed_in_client.get("/api/lessons").json()

        assert [item["id"] for item in body["results"]] == [str(new.id), str(old.id)]
        assert set(body["results"][0]) == {
            "id",
            "topic",
            "stage",
            "route",
            "title",
            "level",
            "entry",
            "intent",
            "sheets_only",
            "followup_level",
            "created_at",
            "updated_at",
            "test_status",
            "test_score",
            "latest_score",
            "best_score",
            "attempts_count",
            "has_open_attempt",
            "material_count",
        }
        assert body["next"] is None and body["previous"] is None

    def test_searches_the_topic_and_filters_by_stage(self, signed_in_client, make_lesson):
        make_lesson(topic="Binary search", stage=Stage.READY)
        make_lesson(topic="Binary trees")
        make_lesson(topic="Amoeba")

        by_text = signed_in_client.get("/api/lessons?q=binary").json()["results"]
        by_stage = signed_in_client.get("/api/lessons?q=binary&stage=ready").json()["results"]

        assert sorted(item["topic"] for item in by_text) == ["Binary search", "Binary trees"]
        assert [item["topic"] for item in by_stage] == ["Binary search"]

    def test_filters_by_several_stages_at_once(self, signed_in_client, make_lesson):
        make_lesson(topic="Waiting", stage=Stage.AWAITING_DIAGNOSTIC)
        make_lesson(topic="Choosing", stage=Stage.AWAITING_CHOICE)
        make_lesson(topic="Done", stage=Stage.READY)
        make_lesson(topic="Broken", stage=Stage.FAILED)

        body = signed_in_client.get("/api/lessons?stage=awaiting_diagnostic, awaiting_choice,nonsense").json()

        assert sorted(item["topic"] for item in body["results"]) == ["Choosing", "Waiting"]

    def test_says_how_the_test_went_and_how_many_sheets_there_are_without_a_query_per_lesson(
        self, signed_in_client, make_lesson, django_assert_max_num_queries
    ):
        graded = make_lesson(topic="Graded", stage=Stage.READY)
        TestSubmission.objects.create(
            lesson=graded, status="graded", result={"score": {"awarded": 7, "available": 10, "percent": 70}}
        )
        grading = make_lesson(topic="Grading", stage=Stage.READY)
        TestSubmission.objects.create(
            lesson=grading, status="grading", result={"score": {"awarded": 1, "available": 10}}
        )
        mastery = make_lesson(topic="Sheets", stage=Stage.READY, route="mastery")
        StudyMaterial.objects.create(lesson=mastery, kind="cheat_sheet", content={})
        StudyMaterial.objects.create(lesson=mastery, kind="revision_sheet", content={})
        for n in range(5):
            make_lesson(topic=f"More {n}")

        with django_assert_max_num_queries(8):
            body = signed_in_client.get("/api/lessons").json()

        by_topic = {item["topic"]: item for item in body["results"]}
        assert (by_topic["Graded"]["test_status"], by_topic["Graded"]["test_score"]) == (
            "graded",
            {"awarded": 7, "available": 10},
        )
        assert (by_topic["Grading"]["test_status"], by_topic["Grading"]["test_score"]) == ("grading", None)
        assert (by_topic["Sheets"]["test_status"], by_topic["Sheets"]["material_count"]) == ("not_started", 2)
        assert by_topic["More 0"]["material_count"] == 0

    def test_pages_with_a_cursor(self, signed_in_client, make_lesson):
        for n in range(5):
            make_lesson(topic=f"Topic {n}")

        first = signed_in_client.get("/api/lessons?page_size=2").json()
        second = signed_in_client.get(first["next"].replace("http://testserver", "")).json()

        assert [i["topic"] for i in first["results"]] == ["Topic 4", "Topic 3"]
        assert [i["topic"] for i in second["results"]] == ["Topic 2", "Topic 1"]
        assert second["previous"] is not None


class TestCreate:
    def test_queues_a_start_run_and_returns_both_ids(self, signed_in_client, user, queue, bound_registry):
        response = signed_in_client.post(
            "/api/lessons", {"topic": " Binary search ", "user_context": "for my exam"}, format="json"
        )

        assert response.status_code == 202
        lesson = Lesson.objects.get(owner=user)
        assert response.json() == {"lesson_id": str(lesson.id), "run_id": str(queue.runs[0].id)}
        assert (lesson.topic, lesson.user_context) == ("Binary search", "for my exam")

    @pytest.mark.parametrize(
        "body", [{}, {"topic": ""}, {"topic": "x"}, {"topic": "t" * 201}, {"topic": "ok", "user_context": "c" * 1001}]
    )
    def test_rejects_a_bad_topic_or_context(self, signed_in_client, queue, bound_registry, body):
        response = signed_in_client.post("/api/lessons", body, format="json")

        assert response.status_code == 400 and response.json()["code"] == "invalid"
        assert Lesson.objects.count() == 0

    def test_a_body_with_a_rating_starts_a_self_rated_lesson(self, signed_in_client, user, queue, bound_registry):
        response = signed_in_client.post(
            "/api/lessons", {"topic": "Binary search", "entry": "self_rating", "self_rating": 3.5}, format="json"
        )

        assert response.status_code == 202
        lesson = Lesson.objects.get(owner=user)
        assert (lesson.entry, lesson.self_rating_halves, lesson.origin, lesson.intent) == (
            "self_rating", 7, "direct", "lesson",
        )  # fmt: skip

    @pytest.mark.parametrize(("stars", "halves"), [(0.5, 1), (1, 2), (2.5, 5), (5, 10), ("4.5", 9)])
    def test_every_half_star_is_stored_as_halves(self, signed_in_client, user, queue, bound_registry, stars, halves):
        body = {"topic": "Binary search", "entry": "self_rating", "self_rating": stars}

        assert signed_in_client.post("/api/lessons", body, format="json").status_code == 202
        assert Lesson.objects.get(owner=user).self_rating_halves == halves

    @pytest.mark.parametrize("body", [
        {"entry": "self_rating"},  # no rating
        {"entry": "self_rating", "self_rating": 0},
        {"entry": "self_rating", "self_rating": 5.5},
        {"entry": "self_rating", "self_rating": 2.3},  # not a half step
        {"entry": "self_rating", "self_rating": "many"},
        {"entry": "self_rating", "self_rating": True},
        {"self_rating": 3},  # a rating goes with its entry
        {"entry": "diagnostic", "self_rating": 3},
        {"entry": "followup"}, {"entry": "quiz_result"}, {"entry": "friend"},
    ])  # fmt: skip
    def test_a_bad_entry_or_rating_is_a_400_that_creates_nothing(self, signed_in_client, queue, bound_registry, body):
        response = signed_in_client.post("/api/lessons", {"topic": "Binary search"} | body, format="json")

        assert response.status_code == 400 and response.json()["code"] == "invalid" and response.json()["fields"]
        assert Lesson.objects.count() == 0 and queue.runs == []

    @pytest.mark.parametrize(("body", "field"), [
        ({"intent": "poster"}, "intent"),
        ({"origin": "followup"}, "origin"),
        ({"origin": "quiz_result"}, "origin"),
        ({"origin": "friend"}, "origin"),
        ({"origin": "recommendation"}, "recommended_from"),
        ({"origin": "recommendation", "recommended_from": {"attempt_id": "x", "topic": "T"}}, "recommended_from"),
        ({"recommended_from": {"attempt_id": str(uuid.uuid4()), "topic": "T"}}, "recommended_from"),
    ])  # fmt: skip
    def test_an_intent_or_origin_that_is_not_allowed_is_a_400_naming_the_field(
        self, signed_in_client, queue, bound_registry, body, field
    ):
        response = signed_in_client.post("/api/lessons", {"topic": "Binary search"} | body, format="json")

        assert response.status_code == 400 and field in response.json()["fields"]
        assert Lesson.objects.count() == 0 and queue.runs == []

    @pytest.mark.parametrize(("extra", "kinds"), [
        ({"sheets": ["cheat_sheet", "revision_sheet"]}, ["cheat_sheet", "revision_sheet"]),
        ({"sheets": ["revision_sheet"]}, ["revision_sheet"]),
        ({"sheets": ["cheat_sheet"], "entry": "self_rating", "self_rating": 2}, ["cheat_sheet"]),
    ])  # fmt: skip
    def test_a_lesson_can_be_asked_for_as_sheets(self, signed_in_client, user, queue, bound_registry, extra, kinds):
        body = {"topic": "Binary search", "intent": "sheets"} | extra

        response = signed_in_client.post("/api/lessons", body, format="json")

        assert response.status_code == 202
        made = Lesson.objects.get(owner=user)
        assert made.intent == "sheets" and made.sheets_only
        assert queue.runs[0].payload["input"] == {"sheet_kinds": kinds}

    @pytest.mark.parametrize("body", [
        {"intent": "sheets"},  # no sheets
        {"intent": "sheets", "sheets": []},
        {"intent": "sheets", "sheets": ["practice_sheet"]},
        {"intent": "sheets", "sheets": ["cheat_sheet", "poster"]},
        {"intent": "sheets", "sheets": ["cheat_sheet", "cheat_sheet"]},
        {"intent": "sheets", "sheets": "cheat_sheet"},
        {"intent": "lesson", "sheets": ["cheat_sheet"]},
        {"sheets": ["cheat_sheet"]},
    ])  # fmt: skip
    def test_sheets_that_do_not_fit_are_a_400_naming_the_field(self, signed_in_client, queue, bound_registry, body):
        response = signed_in_client.post("/api/lessons", {"topic": "Binary search"} | body, format="json")

        assert response.status_code == 400 and "sheets" in response.json()["fields"]
        assert Lesson.objects.count() == 0 and queue.runs == []

    def test_a_lesson_asked_for_as_sheets_needs_the_sheet_writer_bound(self, signed_in_client, queue, db):
        from llm_registry.node_configs import NodeConfigSync

        NodeConfigSync().ensure()
        body = {"topic": "Binary search", "intent": "sheets", "sheets": ["cheat_sheet"], "entry": "self_rating",
                "self_rating": 3}  # fmt: skip

        response = signed_in_client.post("/api/lessons", body, format="json")

        assert response.status_code == 503 and response.json()["code"] == "llm_not_configured"

    def test_a_recommendation_for_the_callers_own_graded_attempt_and_topic_is_stored(
        self, signed_in_client, user, queue, bound_registry, lesson
    ):
        attempt = TestSubmission.objects.create(
            lesson=lesson, status="graded", result={"topics_to_revisit": ["Off by one"], "score": {}}
        )
        body = {
            "topic": "Off by one", "origin": "recommendation",
            "recommended_from": {"attempt_id": str(attempt.pk), "topic": "Off by one"},
        }  # fmt: skip

        response = signed_in_client.post("/api/lessons", body, format="json")

        assert response.status_code == 202
        made = Lesson.objects.get(pk=response.json()["lesson_id"])
        assert made.origin == "recommendation" and made.recommended_from["attempt_id"] == str(attempt.pk)

    def test_a_recommendation_for_another_learners_attempt_is_a_400_like_a_missing_one(
        self, signed_in_client, other_user, make_lesson, queue, bound_registry
    ):
        theirs = TestSubmission.objects.create(
            lesson=make_lesson(owner=other_user), status="graded", result={"topics_to_revisit": ["Off by one"]}
        )
        body = {
            "topic": "Off by one", "origin": "recommendation",
            "recommended_from": {"attempt_id": str(theirs.pk), "topic": "Off by one"},
        }  # fmt: skip

        response = signed_in_client.post("/api/lessons", body, format="json")

        assert response.status_code == 400 and "recommended_from" in response.json()["fields"]
        assert not Lesson.objects.filter(topic="Off by one").exists()

    def test_says_so_when_no_model_is_bound(self, signed_in_client, queue, db):
        from llm_registry.node_configs import NodeConfigSync

        NodeConfigSync().ensure()

        response = signed_in_client.post("/api/lessons", {"topic": "Binary search"}, format="json")

        assert response.status_code == 503 and response.json()["code"] == "llm_not_configured"

    def test_is_rate_limited(self, signed_in_client, queue, bound_registry, monkeypatch):
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "lesson_create", "2/hour")

        statuses = [signed_in_client.post("/api/lessons", {"topic": "Binary search"}, format="json").status_code
                    for _ in range(3)]  # fmt: skip

        assert statuses == [202, 202, 429]


class TestDetail:
    def test_reports_the_stage_the_active_run_and_hides_the_writers_notes(self, signed_in_client, lesson):
        run = GraphRun.objects.create(lesson=lesson, trigger=GraphRun.Trigger.START, status=GraphRun.Status.RUNNING)
        Lesson.objects.filter(pk=lesson.pk).update(
            assessment={"level": "beginner", "level_scheme": 2, "known_concepts": ["a"], "gaps": ["b"],
                        "start_point": "s",
                        "confidence": "high", "author_notes": "secret guidance", "prerequisites_to_cover": []},
            prerequisites_to_cover=[{"name": "Arrays", "why_needed": "x"}],
        )  # fmt: skip

        body = signed_in_client.get(f"/api/lessons/{lesson.id}").json()

        assert body["stage"] == "preparing_diagnostic" and body["active_run_id"] == str(run.id)
        assert body["assessment"]["level"] == "beginner" and "author_notes" not in body["assessment"]
        assert body["prerequisites_to_cover"] == ["Arrays"]
        assert "config_snapshot" not in body and "plan" not in body

    def test_says_how_the_level_was_found(self, signed_in_client, lesson):
        quick = signed_in_client.get(f"/api/lessons/{lesson.id}").json()
        Lesson.objects.filter(pk=lesson.pk).update(
            entry="self_rating", self_rating_halves=7, level="foundation", level_source="self_rating",
            origin="recommendation",
        )  # fmt: skip

        rated = signed_in_client.get(f"/api/lessons/{lesson.id}").json()

        assert (quick["entry"], quick["intent"], quick["origin"], quick["self_rating"], quick["level_source"]) == (
            "diagnostic", "lesson", "direct", None, "",
        )  # fmt: skip
        assert (rated["entry"], rated["self_rating"], rated["level"], rated["level_source"], rated["origin"]) == (
            "self_rating", 3.5, "foundation", "self_rating", "recommendation",
        )  # fmt: skip

    @pytest.mark.parametrize(("fields", "sheets_only"), [
        ({}, False), ({"route": "lesson"}, False), ({"intent": "sheets"}, True), ({"route": "mastery"}, True),
        ({"route": "mastery", "stage": Stage.AWAITING_CHOICE}, False),
    ])  # fmt: skip
    def test_says_whether_the_lesson_is_only_sheets_in_the_detail_and_the_list(
        self, signed_in_client, make_lesson, fields, sheets_only
    ):
        lesson = make_lesson(**fields)

        detail = signed_in_client.get(f"/api/lessons/{lesson.id}").json()
        (row,) = signed_in_client.get("/api/lessons").json()["results"]

        assert detail["sheets_only"] is sheets_only and row["sheets_only"] is sheets_only
        assert row["intent"] == lesson.intent == detail["intent"]

    def test_a_lesson_that_asked_for_sheets_says_which_and_any_other_lesson_says_none(
        self, signed_in_client, make_lesson
    ):
        sheets = make_lesson(intent="sheets")
        GraphRun.objects.create(
            lesson=sheets, trigger=GraphRun.Trigger.START, payload={"input": {"sheet_kinds": ["revision_sheet"]}}
        )
        plain = make_lesson()

        assert signed_in_client.get(f"/api/lessons/{sheets.id}").json()["sheets_asked"] == ["revision_sheet"]
        assert signed_in_client.get(f"/api/lessons/{plain.id}").json()["sheets_asked"] == []

    def test_the_assessment_says_where_it_came_from_when_it_is_known(self, signed_in_client, lesson):
        Lesson.objects.filter(pk=lesson.pk).update(assessment={
            "level": "expert", "level_scheme": 2, "source": "self_rating", "known_concepts": [], "gaps": [],
            "start_point": "s", "confidence": "low",
        })  # fmt: skip

        assert signed_in_client.get(f"/api/lessons/{lesson.id}").json()["assessment"]["source"] == "self_rating"

    def test_an_assessment_written_before_the_level_rename_is_served_in_the_new_names(self, signed_in_client, lesson):
        Lesson.objects.filter(pk=lesson.pk).update(  # no level_scheme: "beginner" meant what is now "foundation"
            assessment={"level": "beginner", "known_concepts": [], "gaps": [], "start_point": "s", "confidence": "low"}
        )

        body = signed_in_client.get(f"/api/lessons/{lesson.id}").json()

        assert body["assessment"]["level"] == "foundation"

    def test_keeps_the_quiz_scores_after_a_reload(self, signed_in_client, lesson):
        quiz = waiting(lesson)
        signed_in_client.post(
            f"/api/lessons/{lesson.id}/quizzes/diagnostic/attempt", {"answers": right_answers(quiz)}, format="json"
        )
        Lesson.objects.filter(pk=lesson.pk).update(route="lesson")
        GraphRun.objects.all().update(status=GraphRun.Status.SUCCEEDED)

        body = signed_in_client.get(f"/api/lessons/{lesson.id}").json()

        assert body["results"]["diagnostic"]["correct"] == 5 and body["results"]["diagnostic"]["route"] == "lesson"
        assert body["results"]["prerequisite"] is None
        assert "per_question" not in body["results"]["diagnostic"]

    @pytest.mark.parametrize(
        ("submission", "status", "score"),
        [
            (None, "not_started", None),
            ({"status": "grading", "result": {"score": {"awarded": 2, "available": 20}}}, "grading", None),
            ({"status": "failed", "result": {"score": {"awarded": 2, "available": 20}}}, "failed", None),
            ({"status": "graded", "result": {"score": {"awarded": 14, "available": 20}}}, "graded",
             {"awarded": 14, "available": 20}),
        ],
    )  # fmt: skip
    def test_reports_the_status_of_the_test_and_its_score_once_graded(
        self, signed_in_client, lesson, submission, status, score
    ):
        if submission:
            TestSubmission.objects.create(lesson=lesson, **submission)

        body = signed_in_client.get(f"/api/lessons/{lesson.id}").json()

        assert (body["test_status"], body["test_score"]) == (status, score)

    def test_another_users_lesson_is_a_404(self, signed_in_client, make_lesson, other_user):
        theirs = make_lesson(owner=other_user)

        for method, path in [("get", ""), ("delete", ""), ("post", "/retry"), ("get", "/quizzes/diagnostic")]:
            assert getattr(signed_in_client, method)(f"/api/lessons/{theirs.id}{path}").status_code == 404

        assert Lesson.objects.filter(pk=theirs.pk).exists()

    @pytest.mark.parametrize("lesson_id", ["not-a-uuid", "00000000-0000-0000-0000-000000000000"])
    def test_an_unknown_or_malformed_id_is_a_404(self, signed_in_client, lesson_id):
        response = signed_in_client.get(f"/api/lessons/{lesson_id}")

        assert response.status_code == 404 and response.json()["code"] == "not_found"


class TestDeleteAndRetry:
    def test_delete_removes_the_lesson(self, signed_in_client, lesson, queue):
        assert signed_in_client.delete(f"/api/lessons/{lesson.id}").status_code == 204
        assert not Lesson.objects.filter(pk=lesson.pk).exists()

    def test_retry_queues_a_run_for_a_failed_lesson(self, signed_in_client, make_lesson, queue):
        lesson = make_lesson(stage=Stage.FAILED, error="boom")

        response = signed_in_client.post(f"/api/lessons/{lesson.id}/retry")

        assert response.status_code == 202 and response.json() == {"run_id": str(queue.runs[0].id)}

    def test_retry_of_a_lesson_that_did_not_fail_is_a_conflict(self, signed_in_client, lesson, queue):
        response = signed_in_client.post(f"/api/lessons/{lesson.id}/retry")

        assert response.status_code == 409 and response.json()["code"] == "wrong_stage"


class TestQuizzes:
    def test_the_quiz_has_no_answers_or_explanations(self, signed_in_client, lesson):
        quiz = waiting(lesson)

        response = signed_in_client.get(f"/api/lessons/{lesson.id}/quizzes/diagnostic")

        body = response.json()
        assert response.status_code == 200 and body["quiz_id"] == str(quiz.id) and len(body["questions"]) == 10
        assert all(set(question) <= {"id", "band", "question", "options"} for question in body["questions"])
        text = json.dumps(body)
        assert "correct_index" not in text and "explanation" not in text

    def test_a_quiz_that_is_not_there_yet_is_a_404(self, signed_in_client, lesson):
        assert signed_in_client.get(f"/api/lessons/{lesson.id}/quizzes/diagnostic").status_code == 404

    def test_answering_returns_the_score_and_route_and_queues_the_resume(self, signed_in_client, lesson, queue):
        quiz = waiting(lesson)

        response = signed_in_client.post(
            f"/api/lessons/{lesson.id}/quizzes/diagnostic/attempt", {"answers": right_answers(quiz, 6)}, format="json"
        )

        body = response.json()
        assert response.status_code == 202
        assert body["result"]["correct"] == 6 and body["result"]["route"] == "lesson"
        assert body["result"]["by_band"]["basic"] == [2, 2]
        assert body["run_id"] == str(queue.runs[0].id)
        assert "per_question" not in body["result"]

    def test_unanswered_questions_are_a_400_with_the_reason(self, signed_in_client, lesson, queue):
        quiz = waiting(lesson)
        answers = right_answers(quiz)
        del answers["q4"]

        response = signed_in_client.post(
            f"/api/lessons/{lesson.id}/quizzes/diagnostic/attempt", {"answers": answers}, format="json"
        )

        assert response.status_code == 400 and "q4" in response.json()["detail"]
        assert QuizAttempt.objects.count() == 0

    def test_a_missing_answers_field_is_a_400(self, signed_in_client, lesson, queue):
        waiting(lesson)

        response = signed_in_client.post(f"/api/lessons/{lesson.id}/quizzes/diagnostic/attempt", {}, format="json")

        assert response.status_code == 400 and "answers" in response.json()["fields"]

    def test_answering_twice_is_a_conflict(self, signed_in_client, lesson, queue):
        quiz = waiting(lesson)
        url = f"/api/lessons/{lesson.id}/quizzes/diagnostic/attempt"
        signed_in_client.post(url, {"answers": right_answers(quiz)}, format="json")
        GraphRun.objects.all().update(status=GraphRun.Status.PAUSED)

        response = signed_in_client.post(url, {"answers": right_answers(quiz)}, format="json")

        assert response.status_code == 409 and response.json()["code"] == "already_attempted"

    def test_answering_a_quiz_the_lesson_is_not_waiting_for_is_a_conflict(self, signed_in_client, lesson, queue):
        quiz = waiting(lesson)
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.GENERATING_LESSON)

        response = signed_in_client.post(
            f"/api/lessons/{lesson.id}/quizzes/diagnostic/attempt", {"answers": right_answers(quiz)}, format="json"
        )

        assert response.status_code == 409 and response.json()["code"] == "wrong_stage"

    def test_answering_twice_is_still_already_attempted_after_the_lesson_has_moved_on(
        self, signed_in_client, lesson, queue
    ):
        quiz = waiting(lesson)
        url = f"/api/lessons/{lesson.id}/quizzes/diagnostic/attempt"
        signed_in_client.post(url, {"answers": right_answers(quiz)}, format="json")
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.GENERATING_LESSON)

        response = signed_in_client.post(url, {"answers": right_answers(quiz, 0)}, format="json")

        assert response.status_code == 409 and response.json()["code"] == "already_attempted"
        assert QuizAttempt.objects.get(quiz=quiz).result["correct"] == 5

    def test_the_review_needs_an_attempt_and_then_shows_the_answers(self, signed_in_client, lesson, queue):
        quiz = waiting(lesson)
        url = f"/api/lessons/{lesson.id}/quizzes/diagnostic/review"
        assert signed_in_client.get(url).status_code == 409

        signed_in_client.post(
            f"/api/lessons/{lesson.id}/quizzes/diagnostic/attempt", {"answers": right_answers(quiz, 4)}, format="json"
        )
        body = signed_in_client.get(url).json()

        assert body["questions"][0]["correct_index"] == 0 and body["questions"][0]["correct"] is True
        assert body["questions"][9]["correct"] is False and body["result"]["correct"] == 4

    def test_the_review_has_everything_the_learner_needs_to_see_where_they_went_wrong(
        self, signed_in_client, lesson, queue
    ):
        quiz = waiting(lesson)
        answers = right_answers(quiz, 4) | {quiz.questions[1]["id"]: "dont_know"}
        signed_in_client.post(
            f"/api/lessons/{lesson.id}/quizzes/diagnostic/attempt", {"answers": answers}, format="json"
        )

        questions = signed_in_client.get(f"/api/lessons/{lesson.id}/quizzes/diagnostic/review").json()["questions"]

        assert len(questions) == len(quiz.questions)
        assert signed_in_client.get(f"/api/lessons/{lesson.id}/quizzes/diagnostic/review").json()["submitted_at"]
        for shown, stored in zip(questions, quiz.questions, strict=True):
            assert {
                key: shown[key] for key in ("id", "band", "question", "options", "correct_index", "explanation")
            } == {key: stored[key] for key in ("id", "band", "question", "options", "correct_index", "explanation")}
            assert shown["answer"] == answers[stored["id"]] and shown["correct"] is (
                shown["answer"] == stored["correct_index"]
            )
        assert questions[1]["answer"] == "dont_know" and questions[1]["correct"] is False


class TestRuns:
    def make_run(self, lesson, status=GraphRun.Status.SUCCEEDED):
        return GraphRun.objects.create(
            lesson=lesson, trigger=GraphRun.Trigger.START, status=status, node_status={"a": "done"}
        )

    def test_reads_a_run(self, signed_in_client, lesson):
        run = self.make_run(lesson)

        body = signed_in_client.get(f"/api/runs/{run.id}").json()

        assert body == {
            "id": str(run.id), "lesson_id": str(lesson.id), "quiz_id": None, "graph": "flow", "trigger": "start",
            "status": "succeeded", "node_status": {"a": "done"}, "error": "",
        }  # fmt: skip

    def test_reads_the_run_of_a_quick_quiz(self, signed_in_client, quiz):
        run = GraphRun.objects.create(quick_quiz=quiz, graph="quick_quiz", trigger="start", status="running")

        body = signed_in_client.get(f"/api/runs/{run.id}").json()

        assert (body["lesson_id"], body["quiz_id"], body["graph"]) == (None, str(quiz.id), "quick_quiz")

    def test_another_learners_quiz_run_is_a_404(self, signed_in_client, make_quiz, other_user):
        quiz = make_quiz(owner=other_user, topic="T")
        theirs = GraphRun.objects.create(quick_quiz=quiz, graph="quick_quiz", trigger="start")

        assert signed_in_client.get(f"/api/runs/{theirs.id}").status_code == 404

    def test_another_users_run_is_a_404(self, signed_in_client, make_lesson, other_user):
        run = self.make_run(make_lesson(owner=other_user))

        for method, suffix in [("get", ""), ("get", "/events"), ("post", "/cancel")]:
            assert getattr(signed_in_client, method)(f"/api/runs/{run.id}{suffix}").status_code == 404

    def test_the_event_stream_of_a_finished_run_ends_after_the_snapshot_and_done(self, signed_in_client, lesson):
        run = self.make_run(lesson)

        response = signed_in_client.get(f"/api/runs/{run.id}/events")
        body = b"".join(async_to_sync(collect)(response)).decode()

        assert response.status_code == 200 and response["Content-Type"] == "text/event-stream"
        assert response["Cache-Control"] == "no-cache"
        assert body.startswith("event: snapshot\n") and "event: done\n" in body
        assert f'"lesson_id": "{lesson.id}"' in body

    def test_a_browsers_event_source_is_served_not_refused_with_406(self, signed_in_client, lesson):
        # Regression: EventSource sends "Accept: text/event-stream", which JSON-only content negotiation refused.
        run = self.make_run(lesson)

        response = signed_in_client.get(f"/api/runs/{run.id}/events", HTTP_ACCEPT="text/event-stream")

        assert response.status_code == 200 and response["Content-Type"] == "text/event-stream"

    def test_errors_on_the_event_stream_are_still_json(self, signed_in_client, make_lesson, other_user):
        run = self.make_run(make_lesson(owner=other_user))

        response = signed_in_client.get(f"/api/runs/{run.id}/events", HTTP_ACCEPT="text/event-stream")

        assert response.status_code == 404 and response.json()["code"] == "not_found"

    def test_cancel_stops_an_active_run_once(self, signed_in_client, lesson):
        run = self.make_run(lesson, GraphRun.Status.RUNNING)

        first = signed_in_client.post(f"/api/runs/{run.id}/cancel")
        second = signed_in_client.post(f"/api/runs/{run.id}/cancel")

        run.refresh_from_db()
        lesson.refresh_from_db()
        assert first.status_code == 202 and second.status_code == 409
        assert run.status == GraphRun.Status.CANCELLED and lesson.stage == Stage.FAILED


class TestMaterials:
    def mastery(self, make_lesson, stage=Stage.READY, **extra):
        return make_lesson(stage=stage, route="mastery", **extra)

    @pytest.mark.parametrize(("body", "resume"), [({"choice": "lesson"}, "lesson"), ({"choice": "sheets"}, "sheets")])
    def test_choosing_resumes_the_flow(self, signed_in_client, make_lesson, queue, body, resume):
        lesson = self.mastery(make_lesson, Stage.AWAITING_CHOICE)

        response = signed_in_client.post(f"/api/lessons/{lesson.id}/choice", body, format="json")

        assert response.status_code == 202 and response.json() == {"run_id": str(queue.runs[0].id)}
        assert queue.runs[0].payload == {"resume": {"choice": resume}}

    @pytest.mark.parametrize("body", [
        {}, {"kind": "poster"}, {"kind": ""}, {"choice": "poster"}, {"choice": "cheat_sheet"},
        {"kind": "cheat_sheet"},  # the old three-sheet choice: no lesson waits at it any more
    ])  # fmt: skip
    def test_choosing_needs_exactly_one_known_choice(self, signed_in_client, make_lesson, queue, body):
        lesson = self.mastery(make_lesson, Stage.AWAITING_CHOICE)

        response = signed_in_client.post(f"/api/lessons/{lesson.id}/choice", body, format="json")

        assert response.status_code == 400 and response.json()["fields"] and queue.runs == []

    def test_choosing_outside_the_choice_is_a_conflict(self, signed_in_client, make_lesson, queue):
        lesson = self.mastery(make_lesson, Stage.GENERATING_MATERIAL)

        response = signed_in_client.post(f"/api/lessons/{lesson.id}/choice", {"choice": "sheets"}, format="json")

        assert response.status_code == 409 and response.json()["code"] == "wrong_stage"

    def test_more_sheets_can_be_requested_once_per_kind(self, signed_in_client, make_lesson, queue):
        lesson = self.mastery(make_lesson)
        StudyMaterial.objects.create(lesson=lesson, kind="cheat_sheet", content=make_cheat_sheet())

        again = signed_in_client.post(f"/api/lessons/{lesson.id}/materials", {"kind": "cheat_sheet"}, format="json")
        fresh = signed_in_client.post(f"/api/lessons/{lesson.id}/materials", {"kind": "revision_sheet"}, format="json")

        assert again.status_code == 409 and again.json()["code"] == "already_exists"
        assert again.json()["kinds"] == ["cheat_sheet"]
        assert fresh.status_code == 202 and queue.runs[0].graph == "study_material"

    def test_any_ready_lesson_can_have_sheets_made_for_it(self, signed_in_client, make_lesson, queue):
        lesson = make_lesson(stage=Stage.READY, route="lesson")

        response = signed_in_client.post(f"/api/lessons/{lesson.id}/materials", {"kind": "cheat_sheet"}, format="json")

        assert response.status_code == 202 and response.json() == {"run_id": str(queue.runs[0].id)}

    def test_both_sheets_can_be_asked_for_at_once_as_one_run(self, signed_in_client, make_lesson, queue):
        lesson = make_lesson(stage=Stage.READY, route="lesson")
        body = {"kinds": ["revision_sheet", "cheat_sheet"]}

        response = signed_in_client.post(f"/api/lessons/{lesson.id}/materials", body, format="json")

        assert response.status_code == 202 and len(queue.runs) == 1
        assert queue.runs[0].payload["input"]["sheet_kinds"] == ["cheat_sheet", "revision_sheet"]

    def test_asking_for_both_while_one_exists_names_it_and_makes_nothing(self, signed_in_client, make_lesson, queue):
        lesson = make_lesson(stage=Stage.READY, route="lesson")
        StudyMaterial.objects.create(lesson=lesson, kind="revision_sheet", content=make_revision_sheet())
        body = {"kinds": ["cheat_sheet", "revision_sheet"]}

        response = signed_in_client.post(f"/api/lessons/{lesson.id}/materials", body, format="json")

        assert response.status_code == 409 and response.json()["kinds"] == ["revision_sheet"]
        assert queue.runs == [] and GraphRun.objects.count() == 0

    @pytest.mark.parametrize("body", [
        {}, {"kind": "practice_sheet"}, {"kind": "poster"}, {"kinds": []}, {"kinds": ["practice_sheet"]},
        {"kinds": ["cheat_sheet", "cheat_sheet"]}, {"kind": "cheat_sheet", "kinds": ["revision_sheet"]},
        {"kinds": "cheat_sheet"},
    ])  # fmt: skip
    def test_the_sheets_asked_for_must_be_one_or_both_of_the_two_offered(
        self, signed_in_client, make_lesson, queue, body
    ):
        lesson = make_lesson(stage=Stage.READY, route="lesson")

        response = signed_in_client.post(f"/api/lessons/{lesson.id}/materials", body, format="json")

        assert response.status_code == 400 and response.json()["fields"] and queue.runs == []

    def test_a_lesson_that_is_not_ready_is_a_conflict(self, signed_in_client, make_lesson, queue):
        lesson = make_lesson(stage=Stage.GENERATING_LESSON)

        response = signed_in_client.post(f"/api/lessons/{lesson.id}/materials", {"kind": "cheat_sheet"}, format="json")

        assert response.status_code == 409 and response.json()["code"] == "wrong_stage"

    def test_lists_the_sheets_with_when_each_was_made(self, signed_in_client, lesson):
        StudyMaterial.objects.create(lesson=lesson, kind="revision_sheet", content={})
        StudyMaterial.objects.create(lesson=lesson, kind="cheat_sheet", content={})

        response = signed_in_client.get(f"/api/lessons/{lesson.id}/materials")

        assert response.status_code == 200
        body = response.json()
        assert [row["kind"] for row in body] == ["revision_sheet", "cheat_sheet"]  # oldest first
        assert all(set(row) == {"kind", "created_at"} and row["created_at"] for row in body)

    def test_a_lesson_with_no_sheets_lists_none_and_another_learners_lesson_is_a_404(
        self, signed_in_client, lesson, make_lesson, other_user
    ):
        theirs = make_lesson(owner=other_user)

        assert signed_in_client.get(f"/api/lessons/{lesson.id}/materials").json() == []
        assert signed_in_client.get(f"/api/lessons/{theirs.id}/materials").status_code == 404

    def test_serves_a_sheet(self, signed_in_client, lesson):
        StudyMaterial.objects.create(lesson=lesson, kind="cheat_sheet", content=make_cheat_sheet())

        body = signed_in_client.get(f"/api/lessons/{lesson.id}/materials/cheat_sheet").json()

        assert body["kind"] == "cheat_sheet" and body["content"]["title"] == "Binary search cheat sheet"

    def test_a_practice_sheet_has_no_solutions_until_revealed(self, signed_in_client, lesson):
        StudyMaterial.objects.create(lesson=lesson, kind="practice_sheet", content=make_practice_sheet())
        url = f"/api/lessons/{lesson.id}/materials/practice_sheet"

        hidden = signed_in_client.get(url).json()
        one = signed_in_client.get(url + "?reveal=t1").json()
        several = signed_in_client.get(url + "?reveal=t1&reveal=t2,t3").json()
        everything = signed_in_client.get(url + "?reveal=all").json()

        assert hidden["solutions"] == {} and "correct_index" not in json.dumps(hidden)
        assert set(one["solutions"]) == {"t1"}
        assert set(several["solutions"]) == {"t1", "t2", "t3"}
        assert len(everything["solutions"]) == 15
        assert "model_answer" not in json.dumps(everything["content"])

    def test_a_sheet_that_does_not_exist_is_a_404(self, signed_in_client, lesson):
        assert signed_in_client.get(f"/api/lessons/{lesson.id}/materials/cheat_sheet").status_code == 404

    def test_grades_a_practice_sheet_on_submit(self, signed_in_client, lesson):
        StudyMaterial.objects.create(lesson=lesson, kind="practice_sheet", content=make_practice_sheet())

        response = signed_in_client.post(
            f"/api/lessons/{lesson.id}/materials/practice_sheet/grade",
            {"answers": {"t1": 1, "t2": "4", "t3": "an essay"}},
            format="json",
        )

        body = response.json()
        assert response.status_code == 200
        assert body["score"]["awarded"] == 3 and body["score"]["open_marks"] == 12  # 1 + 2; the short answers are open
        assert body["results"][0]["solution"]["correct_index"] == 1

    def test_grading_without_answers_is_a_400(self, signed_in_client, lesson):
        StudyMaterial.objects.create(lesson=lesson, kind="practice_sheet", content=make_practice_sheet())

        response = signed_in_client.post(f"/api/lessons/{lesson.id}/materials/practice_sheet/grade", {}, format="json")

        assert response.status_code == 400

    def test_another_users_sheets_are_a_404(self, signed_in_client, make_lesson, other_user):
        theirs = make_lesson(owner=other_user, stage=Stage.READY, route="mastery")
        StudyMaterial.objects.create(lesson=theirs, kind="practice_sheet", content=make_practice_sheet())

        for method, path, body in [
            ("get", "/materials/practice_sheet", None),
            ("post", "/materials/practice_sheet/grade", {"answers": {}}),
            ("post", "/materials", {"kind": "cheat_sheet"}),
            ("post", "/choice", {"choice": "sheets"}),
        ]:
            response = getattr(signed_in_client, method)(
                f"/api/lessons/{theirs.id}{path}", *([body] if body else []), format="json"
            )
            assert response.status_code == 404, path

    def test_the_lesson_detail_lists_its_sheets(self, signed_in_client, lesson):
        StudyMaterial.objects.create(lesson=lesson, kind="revision_sheet", content={})
        StudyMaterial.objects.create(lesson=lesson, kind="cheat_sheet", content={})

        assert signed_in_client.get(f"/api/lessons/{lesson.id}").json()["materials"] == [
            "cheat_sheet",
            "revision_sheet",
        ]


def test_the_openapi_schema_documents_the_lessons_api(api_client):
    paths = api_client.get("/api/schema?format=json").json()["paths"]

    for path in ["/api/lessons", "/api/lessons/{lesson_id}", "/api/lessons/{lesson_id}/retry",
                 "/api/lessons/{lesson_id}/quizzes/{kind}/attempt", "/api/runs/{run_id}/events",
                 "/api/lessons/{lesson_id}/choice", "/api/lessons/{lesson_id}/materials",
                 "/api/lessons/{lesson_id}/materials/{kind}",
                 "/api/lessons/{lesson_id}/materials/practice_sheet/grade", "/api/lessons/{lesson_id}/test",
                 "/api/lessons/{lesson_id}/test/submission",
                 "/api/lessons/{lesson_id}/test/attempts", "/api/lessons/{lesson_id}/test/attempts/{attempt_id}",
                 "/api/lessons/{lesson_id}/test/attempts/{attempt_id}/answers/{question_id}",
                 "/api/lessons/{lesson_id}/test/attempts/{attempt_id}/submit",
                 "/api/lessons/{lesson_id}/test/attempts/{attempt_id}/regrade"]:  # fmt: skip
        assert path in paths


class TestLessonCode:
    @pytest.fixture
    def ready(self, make_lesson):
        return make_lesson(
            stage=Stage.READY, code="CODE v2", code_parts={"pages": {}}, code_version=2,
            settings_snapshot={"max_auto_runtime_repairs": 2}, final_test={"title": "T", "questions": [
                {"id": "t1", "type": "mcq", "concept": "c", "difficulty": "easy", "marks": 1, "question": "q",
                 "options": ["a", "b", "c", "d"], "correct_index": 2, "explanation": "because"}]},
        )  # fmt: skip

    def test_the_document_has_the_code_its_version_and_data_without_answers(self, signed_in_client, ready):
        body = signed_in_client.get(f"/api/lessons/{ready.id}/document").json()

        assert (body["code"], body["code_version"]) == ("CODE v2", 2)
        assert body["data"]["final_test"]["questions"] == []  # the test is its own screen
        assert "correct_index" not in json.dumps(body) and "because" not in json.dumps(body)

    def test_a_new_lesson_has_no_test_inside_its_code(self, signed_in_client, ready):
        assert signed_in_client.get(f"/api/lessons/{ready.id}/document").json()["has_embedded_test"] is False

    def test_an_old_lesson_says_its_code_still_has_the_test_page(self, signed_in_client, ready):
        code = 'const PAGES = [\n  { key: "test", title: "T", render: Page_test },\n];'
        Lesson.objects.filter(pk=ready.pk).update(code=code)

        assert signed_in_client.get(f"/api/lessons/{ready.id}/document").json()["has_embedded_test"] is True

    def test_a_lesson_that_is_not_ready_has_no_document(self, signed_in_client, lesson):
        response = signed_in_client.get(f"/api/lessons/{lesson.id}/document")

        assert response.status_code == 409 and response.json()["code"] == "wrong_stage"

    def test_a_crash_report_queues_a_repair(self, signed_in_client, ready, queue):
        body = {"error": {"message": "Interactive_x crashed", "stack": "at x", "page": "core"}, "code_version": 2}

        response = signed_in_client.post(f"/api/lessons/{ready.id}/repair", body, format="json")

        assert response.status_code == 202
        run = GraphRun.objects.get(pk=response.json()["run_id"])
        assert run.graph == "runtime_repair" and queue.runs == [run]
        assert run.payload["input"] == {"repair_error": body["error"], "expected_code_version": 2}

    @pytest.mark.parametrize(
        "body",
        [{}, {"code_version": 2}, {"error": {"message": ""}, "code_version": 2}, {"error": {"message": "x"}},
         {"error": {"message": "x" * 2001}, "code_version": 2}, {"error": {"message": "x"}, "code_version": -1}],
    )  # fmt: skip
    def test_a_bad_report_is_a_400_and_queues_nothing(self, signed_in_client, ready, queue, body):
        response = signed_in_client.post(f"/api/lessons/{ready.id}/repair", body, format="json")

        assert response.status_code == 400 and queue.runs == []

    def test_a_stale_version_and_the_cap_are_conflicts(self, signed_in_client, ready, queue):
        report = {"error": {"message": "boom"}, "code_version": 2}
        stale = signed_in_client.post(f"/api/lessons/{ready.id}/repair", report | {"code_version": 1}, format="json")
        Lesson.objects.filter(pk=ready.pk).update(runtime_repairs=2)
        capped = signed_in_client.post(f"/api/lessons/{ready.id}/repair", report, format="json")

        assert (stale.status_code, stale.json()["code"]) == (409, "stale_code_version")
        assert (capped.status_code, capped.json()["code"]) == (409, "repair_limit_reached") and queue.runs == []

    def test_versions_are_listed_newest_first_without_code(self, signed_in_client, ready):
        for number in (1, 2):
            LessonVersion.objects.create(lesson=ready, code_version=number, code=f"c{number}", reason=f"r{number}")

        body = signed_in_client.get(f"/api/lessons/{ready.id}/versions").json()

        assert [v["code_version"] for v in body] == [2, 1] and body[0]["reason"] == "r2"
        assert "code" not in body[0] and "created_at" in body[0]

    def test_a_version_can_be_restored(self, signed_in_client, ready):
        LessonVersion.objects.create(lesson=ready, code_version=1, code="CODE v1", reason="r")

        response = signed_in_client.post(f"/api/lessons/{ready.id}/versions/1/restore")

        assert response.status_code == 200 and response.json() == {"code_version": 3}
        assert Lesson.objects.get(pk=ready.pk).code == "CODE v1"

    def test_restoring_a_version_that_does_not_exist_is_a_404(self, signed_in_client, ready):
        assert signed_in_client.post(f"/api/lessons/{ready.id}/versions/7/restore").status_code == 404

    def test_another_users_lesson_is_a_404_everywhere(self, signed_in_client, other_user, make_lesson):
        theirs = make_lesson(owner=other_user, stage=Stage.READY, code="x", code_version=1)
        base = f"/api/lessons/{theirs.id}"
        report = {"error": {"message": "x"}, "code_version": 1}

        statuses = [
            signed_in_client.get(f"{base}/document").status_code,
            signed_in_client.post(f"{base}/repair", report, format="json").status_code,
            signed_in_client.get(f"{base}/versions").status_code,
            signed_in_client.post(f"{base}/versions/1/restore").status_code,
        ]  # fmt: skip

        assert statuses == [404, 404, 404, 404]


class TestLessonTest:
    FINAL = make_final_test()
    IDS = {q["type"]: q["id"] for q in FINAL["questions"]}

    @property
    def mcq_marks(self) -> int:
        return next(q["marks"] for q in self.FINAL["questions"] if q["id"] == self.IDS["mcq"])

    @pytest.fixture
    def ready(self, make_lesson):
        return make_lesson(stage=Stage.READY, code="x", code_version=1, final_test=self.FINAL)

    def url(self, lesson, suffix=""):
        return f"/api/lessons/{lesson.id}/test/submissions{suffix}"

    @staticmethod
    def go(client, lesson, answers):
        """Attempt 1 started and handed in with `answers` → the reply to the hand-in (or to the start if refused)."""
        started = client.post(f"/api/lessons/{lesson.id}/test/attempts")
        if started.status_code not in (200, 201):
            return started
        attempt = started.json()["attempt_id"]
        return client.post(
            f"/api/lessons/{lesson.id}/test/attempts/{attempt}/submit", {"answers": answers}, format="json"
        )

    def regrade(self, lesson, attempt):
        return f"/api/lessons/{lesson.id}/test/attempts/{attempt.id}/regrade"

    def test_the_test_is_served_without_answers_and_with_its_total_marks(self, signed_in_client, ready):
        signed_in_client.post(f"/api/lessons/{ready.id}/test/attempts")  # attempt 1 starts; the test is its questions
        response = signed_in_client.get(f"/api/lessons/{ready.id}/test")

        body = response.json()
        assert response.status_code == 200 and body["submission"]["status"] == "in_progress"
        assert [q["id"] for q in body["questions"]] == [q["id"] for q in self.FINAL["questions"]]
        assert body["total_marks"] == sum(q["marks"] for q in self.FINAL["questions"])
        leaks = (
            "correct_index",
            "model_answer",
            "key_points",
            "rubric",
            "reference_solution",
            "test_cases",
            "tolerance",
        )
        assert not [word for word in leaks if word in json.dumps(body)]
        assert {"id", "type", "question", "marks"} <= set(body["questions"][0])

    def test_the_test_names_the_one_submission_once_made(self, signed_in_client, ready, queue):
        made = self.go(signed_in_client, ready, {self.IDS["short_answer"]: "x"})

        shown = signed_in_client.get(f"/api/lessons/{ready.id}/test").json()["submission"]

        assert shown["id"] == made.json()["submission_id"] and shown["status"] == "grading"
        assert set(shown) == {"id", "status", "submitted_at"}

    def test_the_test_is_a_conflict_for_a_lesson_that_is_not_ready_or_is_mastery(
        self, signed_in_client, lesson, make_lesson
    ):
        mastery = make_lesson(stage=Stage.READY, code="x", final_test=self.FINAL, route="mastery")

        responses = [signed_in_client.get(f"/api/lessons/{target.id}/test") for target in (lesson, mastery)]

        assert [(r.status_code, r.json()["code"]) for r in responses] == [(409, "wrong_stage")] * 2

    def test_a_submission_is_marked_at_once_and_queued_for_grading(self, signed_in_client, ready, queue):
        answers = {self.IDS["mcq"]: 1, self.IDS["short_answer"]: "Halve it."}

        response = self.go(signed_in_client, ready, answers)

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "grading" and queue.runs[0].graph == "grade_test"
        assert body["run_id"] == str(queue.runs[0].id)
        submission = signed_in_client.get(self.url(ready, f"/{body['submission_id']}")).json()
        assert submission["status"] == "grading" and submission["result"]["complete"] is False
        assert submission["result"]["score"]["awarded"] == self.mcq_marks and submission["graded_at"] is None

    def test_a_test_with_nothing_to_grade_is_final_and_has_no_run(self, signed_in_client, ready, queue):
        response = self.go(signed_in_client, ready, {self.IDS["mcq"]: 1})

        body = response.json()
        assert response.status_code == 200 and body["run_id"] is None and body["status"] == "graded"
        assert queue.runs == []
        result = signed_in_client.get(self.url(ready, f"/{body['submission_id']}")).json()["result"]
        assert result["complete"] is True and result["questions"][0]["solution"] == {"correct_index": 1}

    @pytest.mark.parametrize("answers", [[], {"nope": 1}, {"t1": True}])
    def test_bad_answers_are_a_400(self, signed_in_client, ready, queue, answers):
        response = self.go(signed_in_client, ready, answers)

        assert response.status_code == 400 and queue.runs == []
        assert TestSubmission.objects.get().status == "in_progress"  # the attempt is open and unchanged

    def test_a_lesson_that_is_not_ready_is_a_conflict(self, signed_in_client, lesson, queue):
        early = self.go(signed_in_client, lesson, {})

        assert (early.status_code, early.json()["code"]) == (409, "wrong_stage")

    def test_an_unknown_submission_is_a_404(self, signed_in_client, ready):
        for wrong in ("not-a-uuid", "00000000-0000-0000-0000-000000000000"):
            assert signed_in_client.get(self.url(ready, f"/{wrong}")).status_code == 404

    def test_the_lessons_one_submission_can_be_read_without_its_id(self, signed_in_client, ready, queue):
        assert signed_in_client.get(f"/api/lessons/{ready.id}/test/submission").status_code == 404
        made = self.go(signed_in_client, ready, {self.IDS["mcq"]: 1}).json()

        response = signed_in_client.get(f"/api/lessons/{ready.id}/test/submission")

        body = response.json()
        assert response.status_code == 200 and body["id"] == made["submission_id"] and body["status"] == "graded"
        assert body["answers"] == {self.IDS["mcq"]: 1}  # the learner's own answers, for the read-only result
        assert body["result"]["complete"] is True and body["result"]["score"]["awarded"] == self.mcq_marks

    def test_a_failed_grading_is_run_again_on_the_same_answers(self, signed_in_client, ready, queue):
        failed = TestSubmission.objects.create(
            lesson=ready, answers={self.IDS["short_answer"]: "x"}, status="failed", error="boom"
        )

        response = signed_in_client.post(self.regrade(ready, failed))

        assert response.status_code == 202 and response.json() == {"run_id": str(queue.runs[0].id)}
        failed.refresh_from_db()
        assert (failed.status, failed.answers) == ("grading", {self.IDS["short_answer"]: "x"})

    @pytest.mark.parametrize("status", ["grading", "graded"])
    def test_only_a_failed_grading_can_be_run_again(self, signed_in_client, ready, queue, status):
        submission = TestSubmission.objects.create(lesson=ready, status=status)

        response = signed_in_client.post(self.regrade(ready, submission))

        assert (response.status_code, response.json()["code"]) == (409, "not_failed") and queue.runs == []

    def test_another_users_lesson_and_submission_are_a_404(self, signed_in_client, other_user, make_lesson):
        theirs = make_lesson(owner=other_user, stage=Stage.READY, code="x", final_test=self.FINAL)
        submission = TestSubmission.objects.create(lesson=theirs, status="failed")

        statuses = [
            signed_in_client.get(f"/api/lessons/{theirs.id}/test").status_code,
            self.go(signed_in_client, theirs, {}).status_code,
            signed_in_client.get(self.url(theirs, f"/{submission.id}")).status_code,
            signed_in_client.get(f"/api/lessons/{theirs.id}/test/submission").status_code,
            signed_in_client.post(self.regrade(theirs, submission)).status_code,
        ]

        assert statuses == [404] * 5 and TestSubmission.objects.get().status == "failed"
