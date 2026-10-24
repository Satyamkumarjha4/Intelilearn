"""Unit under test: the lessons API views (`/api/lessons`, `/api/lessons/{id}/quizzes/...`, `/api/runs/{id}`), as the
browser uses them.

Why: this is the boundary where strangers' requests meet a learner's data. A missing ownership filter shows one learner
another's lesson; a quiz that leaks `correct_index` lets the diagnostic be passed by reading the network tab; a wrong
status code makes the UI misread a conflict as a failure.

Use cases:
- every endpoint requires a signed-in user
- listing shows only your own lessons, newest first, with search and stage filters and cursor pagination
- starting a lesson validates the topic, queues a run, is rate limited, and reports an unconfigured registry
- a lesson's detail hides the page writers' notes, reports the active run and keeps the quiz scores after a reload
- another user's lesson, quiz or run is a 404, and so is an id that is not a UUID
- deleting a lesson removes it; retrying is only for failed lessons
- the quiz has no answers; answering returns the score and route; bad, repeated or early answers get 400 and 409
- the review is available only after answering
- a run can be read, followed as an event stream (a finished run ends it at once) and cancelled once
- the OpenAPI schema documents these endpoints
"""

import json

import pytest
from asgiref.sync import async_to_sync
from rest_framework.throttling import SimpleRateThrottle
from support.quiz_data import make_questions

from lessons.models import GraphRun, Lesson, Quiz, QuizAttempt, Stage

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
            "created_at",
            "updated_at",
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
            assessment={"level": "beginner", "known_concepts": ["a"], "gaps": ["b"], "start_point": "s",
                        "confidence": "high", "author_notes": "secret guidance", "prerequisites_to_cover": []},
            prerequisites_to_cover=[{"name": "Arrays", "why_needed": "x"}],
        )  # fmt: skip

        body = signed_in_client.get(f"/api/lessons/{lesson.id}").json()

        assert body["stage"] == "preparing_diagnostic" and body["active_run_id"] == str(run.id)
        assert body["assessment"]["level"] == "beginner" and "author_notes" not in body["assessment"]
        assert body["prerequisites_to_cover"] == ["Arrays"]
        assert "config_snapshot" not in body and "plan" not in body

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

        assert response.status_code == 409 and response.json()["code"] in {"already_attempted", "wrong_stage"}

    def test_answering_a_quiz_the_lesson_is_not_waiting_for_is_a_conflict(self, signed_in_client, lesson, queue):
        quiz = waiting(lesson)
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.GENERATING_LESSON)

        response = signed_in_client.post(
            f"/api/lessons/{lesson.id}/quizzes/diagnostic/attempt", {"answers": right_answers(quiz)}, format="json"
        )

        assert response.status_code == 409 and response.json()["code"] == "wrong_stage"

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


class TestRuns:
    def make_run(self, lesson, status=GraphRun.Status.SUCCEEDED):
        return GraphRun.objects.create(
            lesson=lesson, trigger=GraphRun.Trigger.START, status=status, node_status={"a": "done"}
        )

    def test_reads_a_run(self, signed_in_client, lesson):
        run = self.make_run(lesson)

        body = signed_in_client.get(f"/api/runs/{run.id}").json()

        assert body == {
            "id": str(run.id), "lesson_id": str(lesson.id), "graph": "flow", "trigger": "start",
            "status": "succeeded", "node_status": {"a": "done"}, "error": "",
        }  # fmt: skip

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

    def test_cancel_stops_an_active_run_once(self, signed_in_client, lesson):
        run = self.make_run(lesson, GraphRun.Status.RUNNING)

        first = signed_in_client.post(f"/api/runs/{run.id}/cancel")
        second = signed_in_client.post(f"/api/runs/{run.id}/cancel")

        run.refresh_from_db()
        lesson.refresh_from_db()
        assert first.status_code == 202 and second.status_code == 409
        assert run.status == GraphRun.Status.CANCELLED and lesson.stage == Stage.FAILED


def test_the_openapi_schema_documents_the_lessons_api(api_client):
    paths = api_client.get("/api/schema?format=json").json()["paths"]

    for path in ["/api/lessons", "/api/lessons/{lesson_id}", "/api/lessons/{lesson_id}/retry",
                 "/api/lessons/{lesson_id}/quizzes/{kind}/attempt", "/api/runs/{run_id}/events"]:  # fmt: skip
        assert path in paths
