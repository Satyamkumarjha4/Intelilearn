"""Unit under test: the attempts endpoints (`/api/lessons/{id}/test/attempts...`, `/api/lessons/{id}/test`), as the
browser uses them.

Why: this is where a learner's test meets the network. A start that is answered twice must be one attempt and one
authorization; an answer that can be changed after the learner moved on breaks forward-only; a question that arrives
with its key lets the test be passed by reading the network tab; a lesson that is not the caller's must be a 404; and
the costly start must be rate limited.

Use cases:
- start: attempt 1 is a 201 with its questions and no keys; a repeat is a 200 with the same attempt and its saved
  answers; a retake is a 202 with a run id and no questions, and a repeat returns the same attempt and run
- the Idempotency-Key makes a repeated retake start return the first answer and ask the gate once
- start is rate limited, and a retake past the lesson's daily limit is a 429; a refused action creates nothing
- answer: a saved answer locks its question (a second PUT is a 409 `locked`), a bad shape is a 400, and a sealed or
  preparing attempt is a 409
- submit: a lesson attempt is graded in the same request (200, score, band, offer, the card), a sealed one is a 409
  `attempt_sealed`, the answers sent with it fill only unlocked questions
- the attempt can be read afterwards with its answers and card; the history lists the attempts and the trend
- GET test never starts anything and shows the open attempt only
- another user's lesson and attempt are a 404, and no response carries an answer key
- the lesson summary says how many attempts, the best and latest score, and whether one is open
- the old single call keeps working for the first attempt
"""

import json

import pytest
from rest_framework.throttling import SimpleRateThrottle
from support.gates import RefusingGate, SharedCountingGate
from support.lesson_data import make_blueprint_test, make_plan

from lessons.models import Stage, TestSubmission

pytestmark = pytest.mark.django_db

TEST = make_blueprint_test()
QUESTIONS = TEST["questions"]
LEAKS = ("correct_index", "correct_indices", "answer_expr", "tolerance", "model_answer", "criteria", "explanation")


def right(question):
    field = {"mcq": "correct_index", "msq": "correct_indices", "numerical": "answer"}[question["type"]]
    return question[field]


ALL_RIGHT = {q["id"]: right(q) for q in QUESTIONS}


@pytest.fixture
def ready(make_lesson):
    return make_lesson(
        stage=Stage.READY, code="x", code_version=1, final_test=TEST, plan=make_plan(), settings_snapshot={}
    )


@pytest.fixture(autouse=True)
def gate(settings):
    SharedCountingGate.reset()
    settings.ACTION_GATE = "support.gates.SharedCountingGate"
    return SharedCountingGate


def attempts_url(lesson, suffix=""):
    return f"/api/lessons/{lesson.id}/test/attempts{suffix}"


def first_attempt(client, lesson):
    return client.post(attempts_url(lesson)).json()


def graded(lesson, number, awarded):
    return TestSubmission.objects.create(
        lesson=lesson, attempt_no=number, status="graded", awarded=awarded, available=20, questions=QUESTIONS,
        result={
            "complete": True, "score": {"awarded": awarded, "available": 20, "percent": 0}, "questions": [],
            "topics_to_revisit": [],
        },
    )  # fmt: skip


class TestStart:
    def test_the_first_attempt_is_a_201_with_its_questions_and_no_keys(self, signed_in_client, ready, queue, gate):
        response = signed_in_client.post(attempts_url(ready))

        body = response.json()
        assert response.status_code == 201 and body["attempt_no"] == 1 and body["status"] == "in_progress"
        assert body["run_id"] is None and body["total_marks"] == 20 and body["answers"] == {}
        assert [q["id"] for q in body["questions"]] == [q["id"] for q in QUESTIONS]
        assert not [word for word in LEAKS if word in json.dumps(body)]
        assert gate.authorized == [] and queue.runs == []

    def test_a_repeat_returns_the_same_attempt_with_its_saved_answers(self, signed_in_client, ready, queue):
        first = first_attempt(signed_in_client, ready)
        signed_in_client.put(attempts_url(ready, f"/{first['attempt_id']}/answers/t1"), {"answer": 1}, format="json")

        response = signed_in_client.post(attempts_url(ready))

        body = response.json()
        assert (
            response.status_code == 200 and body["attempt_id"] == first["attempt_id"] and body["answers"] == {"t1": 1}
        )
        assert TestSubmission.objects.filter(lesson=ready).count() == 1

    def test_a_retake_is_a_202_with_a_run_and_no_questions_and_asks_the_gate_once(
        self, signed_in_client, ready, queue, gate
    ):
        graded(ready, 1, 14)

        response = signed_in_client.post(attempts_url(ready))

        body = response.json()
        assert response.status_code == 202 and body["attempt_no"] == 2 and body["status"] == "generating"
        assert body["questions"] == [] and body["total_marks"] == 0
        run = queue.runs[0]
        assert body["run_id"] == str(run.id) and (run.graph, run.trigger) == ("question_bank", "retake")
        assert gate.actions_asked() == ["test.retake"] if hasattr(gate, "actions_asked") else len(gate.authorized) == 1

    def test_a_repeated_retake_start_returns_the_same_attempt_and_run_and_asks_nothing_more(
        self, signed_in_client, ready, queue, gate
    ):
        graded(ready, 1, 14)
        first = signed_in_client.post(attempts_url(ready)).json()

        again = signed_in_client.post(attempts_url(ready))

        assert again.status_code == 202 and again.json()["attempt_id"] == first["attempt_id"]
        assert again.json()["run_id"] == first["run_id"] and len(gate.authorized) == 1 and len(queue.runs) == 1

    def test_the_same_idempotency_key_returns_the_first_answer_and_the_gate_is_asked_once(
        self, signed_in_client, ready, queue, gate
    ):
        graded(ready, 1, 14)
        first = signed_in_client.post(attempts_url(ready), HTTP_IDEMPOTENCY_KEY="abc")
        TestSubmission.objects.filter(lesson=ready, attempt_no=2).delete()  # even if the row is gone, the key replays

        again = signed_in_client.post(attempts_url(ready), HTTP_IDEMPOTENCY_KEY="abc")

        assert again.status_code == first.status_code == 202 and again.json() == first.json()
        assert again["Idempotent-Replayed"] == "true" and len(gate.authorized) == 1

    def test_a_refused_action_creates_nothing(self, signed_in_client, ready, queue, settings):
        graded(ready, 1, 14)
        settings.ACTION_GATE = "support.gates.RefusingGate"

        response = signed_in_client.post(attempts_url(ready))

        assert response.status_code == 403 and response.json()["code"] == "test_refused"
        assert TestSubmission.objects.filter(lesson=ready).count() == 1 and queue.runs == []

    def test_a_retake_past_the_daily_limit_is_a_429(self, signed_in_client, make_lesson, queue):
        lesson = make_lesson(
            stage=Stage.READY, code="x", final_test=TEST, plan=make_plan(), settings_snapshot={"retakes_per_day": 1}
        )
        graded(lesson, 1, 14)
        graded(lesson, 2, 15)

        response = signed_in_client.post(attempts_url(lesson))

        assert response.status_code == 429 and response.json()["code"] == "retake_limit" and queue.runs == []

    def test_starting_is_rate_limited(self, signed_in_client, make_lesson, queue, monkeypatch):
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "test_attempt", "2/hour")
        lessons = [make_lesson(stage=Stage.READY, code="x", final_test=TEST) for _ in range(3)]

        codes = [signed_in_client.post(attempts_url(one)).status_code for one in lessons]

        assert codes == [201, 201, 429]

    @pytest.mark.parametrize("fields", [{"stage": Stage.GENERATING_LESSON}, {"route": "mastery"}])
    def test_a_lesson_that_is_not_ready_or_is_mastery_is_a_409(self, signed_in_client, make_lesson, queue, fields):
        lesson = make_lesson(**({"stage": Stage.READY, "final_test": TEST} | fields))

        response = signed_in_client.post(attempts_url(lesson))

        assert (response.status_code, response.json()["code"]) == (409, "wrong_stage")


class TestAnswer:
    def put(self, client, lesson, attempt, question, answer):
        return client.put(attempts_url(lesson, f"/{attempt}/answers/{question}"), {"answer": answer}, format="json")

    def test_a_saved_answer_locks_its_question(self, signed_in_client, ready, queue):
        attempt = first_attempt(signed_in_client, ready)["attempt_id"]

        saved = self.put(signed_in_client, ready, attempt, "t1", 1)
        again = self.put(signed_in_client, ready, attempt, "t1", 2)

        assert saved.status_code == 200 and saved.json() == {
            "attempt_id": attempt, "question_id": "t1", "locked": True, "answered": 1,
        }  # fmt: skip
        assert (again.status_code, again.json()["code"]) == (409, "locked")
        assert TestSubmission.objects.get(pk=attempt).answers == {"t1": 1}

    def test_a_blank_answer_locks_too(self, signed_in_client, ready, queue):
        attempt = first_attempt(signed_in_client, ready)["attempt_id"]

        assert self.put(signed_in_client, ready, attempt, "t1", None).status_code == 200
        assert self.put(signed_in_client, ready, attempt, "t1", 1).json()["code"] == "locked"

    @pytest.mark.parametrize(
        ("question", "answer"), [("t99", 1), ("t1", {"a": 1}), ("t1", [True]), ("t1", "x" * 10_001)]
    )
    def test_an_unknown_question_or_a_bad_shape_is_a_400(self, signed_in_client, ready, queue, question, answer):
        attempt = first_attempt(signed_in_client, ready)["attempt_id"]

        response = self.put(signed_in_client, ready, attempt, question, answer)

        assert (response.status_code, response.json()["code"]) == (400, "invalid_answers")

    def test_the_body_must_carry_an_answer(self, signed_in_client, ready, queue):
        attempt = first_attempt(signed_in_client, ready)["attempt_id"]

        assert signed_in_client.put(attempts_url(ready, f"/{attempt}/answers/t1"), {}, format="json").status_code == 400

    def test_an_attempt_that_is_still_preparing_is_a_409(self, signed_in_client, ready, queue):
        graded(ready, 1, 14)
        waiting = signed_in_client.post(attempts_url(ready)).json()["attempt_id"]

        response = self.put(signed_in_client, ready, waiting, "t1", 1)

        assert (response.status_code, response.json()["code"]) == (409, "wrong_stage")

    def test_a_sealed_attempt_takes_no_answers(self, signed_in_client, ready, queue):
        attempt = first_attempt(signed_in_client, ready)["attempt_id"]
        signed_in_client.post(attempts_url(ready, f"/{attempt}/submit"), {}, format="json")

        response = self.put(signed_in_client, ready, attempt, "t1", 1)

        assert (response.status_code, response.json()["code"]) == (409, "attempt_sealed")


class TestSubmit:
    def test_a_lesson_attempt_is_graded_in_the_same_request(self, signed_in_client, ready, queue):
        attempt = first_attempt(signed_in_client, ready)["attempt_id"]

        response = signed_in_client.post(
            attempts_url(ready, f"/{attempt}/submit"), {"answers": ALL_RIGHT}, format="json"
        )

        body = response.json()
        assert response.status_code == 200 and body["run_id"] is None and queue.runs == []
        assert (body["status"], body["awarded"], body["available"], body["band"]) == ("graded", 20, 20, "excellent")
        assert body["followup"] is None and body["attempt_no"] == 1 and body["submission_id"] == attempt
        assert body["result"]["complete"] is True and body["result"]["score"]["percent"] == 100

    def test_a_submit_with_no_body_seals_what_was_saved(self, signed_in_client, ready, queue):
        attempt = first_attempt(signed_in_client, ready)["attempt_id"]
        signed_in_client.put(attempts_url(ready, f"/{attempt}/answers/t1"), {"answer": 1}, format="json")

        response = signed_in_client.post(attempts_url(ready, f"/{attempt}/submit"))

        assert response.status_code == 200 and response.json()["awarded"] == 1

    def test_a_second_submit_is_a_409_and_changes_nothing(self, signed_in_client, ready, queue):
        attempt = first_attempt(signed_in_client, ready)["attempt_id"]
        signed_in_client.post(attempts_url(ready, f"/{attempt}/submit"), {"answers": ALL_RIGHT}, format="json")

        again = signed_in_client.post(attempts_url(ready, f"/{attempt}/submit"), {"answers": {}}, format="json")

        assert (again.status_code, again.json()["code"]) == (409, "attempt_sealed")
        assert TestSubmission.objects.get(pk=attempt).awarded == 20

    def test_a_bad_body_is_a_400_and_nothing_is_sealed(self, signed_in_client, ready, queue):
        attempt = first_attempt(signed_in_client, ready)["attempt_id"]

        bad = signed_in_client.post(attempts_url(ready, f"/{attempt}/submit"), {"answers": {"nope": 1}}, format="json")

        assert bad.status_code == 400 and TestSubmission.objects.get(pk=attempt).status == "in_progress"

    def test_an_attempt_of_blank_answers_is_stored_and_scores_zero(self, signed_in_client, ready, queue):
        attempt = first_attempt(signed_in_client, ready)["attempt_id"]

        body = signed_in_client.post(attempts_url(ready, f"/{attempt}/submit")).json()

        assert (body["status"], body["awarded"], body["band"]) == ("graded", 0, "fail")
        assert TestSubmission.objects.get(pk=attempt).all_blank is True


class TestRead:
    def test_the_attempt_can_be_read_with_its_answers_and_card(self, signed_in_client, ready, queue):
        attempt = first_attempt(signed_in_client, ready)["attempt_id"]
        signed_in_client.post(attempts_url(ready, f"/{attempt}/submit"), {"answers": ALL_RIGHT}, format="json")

        body = signed_in_client.get(attempts_url(ready, f"/{attempt}")).json()

        assert body["id"] == attempt and body["attempt_no"] == 1 and body["answers"] == ALL_RIGHT
        assert (body["awarded"], body["band"], body["duration_s"] is not None) == (20, "excellent", True)
        assert body["result"]["questions"][0]["solution"] == {"correct_index": QUESTIONS[0]["correct_index"]}
        assert [q["id"] for q in body["questions"]] == [q["id"] for q in QUESTIONS]  # for the read-only result
        assert not [word for word in LEAKS if word in json.dumps(body["questions"])]

    def test_an_attempt_that_is_still_open_does_not_serve_its_questions_here(self, signed_in_client, ready, queue):
        attempt = first_attempt(signed_in_client, ready)["attempt_id"]

        assert signed_in_client.get(attempts_url(ready, f"/{attempt}")).json()["questions"] == []

    def test_the_history_lists_the_attempts_and_the_trend(self, signed_in_client, ready):
        graded(ready, 1, 10)
        graded(ready, 2, 16)

        body = signed_in_client.get(attempts_url(ready)).json()

        assert [a["attempt_no"] for a in body["attempts"]] == [1, 2] and [a["percent"] for a in body["attempts"]] == [
            50,
            80,
        ]
        assert body["trend"]["best_attempt_no"] == 2 and body["trend"]["series"][1]["delta_previous"] == 30
        assert body["trend"]["series"][1]["delta_best"] == 30 and body["trend"]["series"][0]["delta_previous"] is None

    def test_get_test_shows_the_open_attempt_only_and_starts_nothing(self, signed_in_client, ready, queue, gate):
        before = signed_in_client.get(f"/api/lessons/{ready.id}/test").json()
        started = first_attempt(signed_in_client, ready)
        signed_in_client.put(attempts_url(ready, f"/{started['attempt_id']}/answers/t3"), {"answer": 1}, format="json")

        shown = signed_in_client.get(f"/api/lessons/{ready.id}/test").json()

        assert before["questions"] == [] and before["next_attempt_no"] == 1 and before["attempt"] is None
        assert shown["attempt"]["id"] == started["attempt_id"] and shown["answers"] == {"t3": 1}
        assert len(shown["questions"]) == 10 and not [w for w in LEAKS if w in json.dumps(shown)]
        assert TestSubmission.objects.filter(lesson=ready).count() == 1 and gate.authorized == []

    def test_the_latest_attempt_is_read_without_its_id(self, signed_in_client, ready):
        graded(ready, 1, 10)
        graded(ready, 2, 16)

        body = signed_in_client.get(f"/api/lessons/{ready.id}/test/submission").json()

        assert body["attempt_no"] == 2 and body["awarded"] == 16


class TestOwnership:
    def test_another_users_lesson_and_attempt_are_a_404(self, signed_in_client, other_user, make_lesson, queue):
        theirs = make_lesson(owner=other_user, stage=Stage.READY, code="x", final_test=TEST)
        attempt = TestSubmission.objects.create(lesson=theirs, status="in_progress", questions=QUESTIONS)

        responses = [
            signed_in_client.post(attempts_url(theirs)),
            signed_in_client.get(attempts_url(theirs)),
            signed_in_client.get(attempts_url(theirs, f"/{attempt.id}")),
            signed_in_client.put(attempts_url(theirs, f"/{attempt.id}/answers/t1"), {"answer": 1}, format="json"),
            signed_in_client.post(attempts_url(theirs, f"/{attempt.id}/submit")),
            signed_in_client.post(attempts_url(theirs, f"/{attempt.id}/regrade")),
        ]

        assert [r.status_code for r in responses] == [404] * 6
        assert TestSubmission.objects.get(pk=attempt.pk).answers == {}

    def test_my_attempt_through_a_lesson_that_is_not_its_own_is_a_404(
        self, signed_in_client, ready, make_lesson, queue
    ):
        mine = first_attempt(signed_in_client, ready)["attempt_id"]
        other = make_lesson(stage=Stage.READY, code="x", final_test=TEST)

        response = signed_in_client.get(attempts_url(other, f"/{mine}"))

        assert response.status_code == 404

    @pytest.mark.parametrize("attempt_id", ["not-a-uuid", "00000000-0000-0000-0000-000000000000"])
    def test_an_unknown_attempt_is_a_404(self, signed_in_client, ready, attempt_id):
        assert signed_in_client.get(attempts_url(ready, f"/{attempt_id}")).status_code == 404

    def test_the_endpoints_need_a_signed_in_user(self, api_client, ready):
        assert api_client.post(attempts_url(ready)).status_code in (401, 403)


class TestRegrade:
    def test_a_failed_legacy_grading_is_run_again_on_the_same_answers(self, signed_in_client, ready, queue):
        failed = TestSubmission.objects.create(lesson=ready, answers={"t1": "x"}, status="failed", error="boom")

        response = signed_in_client.post(attempts_url(ready, f"/{failed.id}/regrade"))

        assert response.status_code == 202 and response.json() == {"run_id": str(queue.runs[0].id)}
        failed.refresh_from_db()
        assert (failed.status, failed.answers) == ("grading", {"t1": "x"})


class TestLessonSummary:
    def test_the_summary_counts_attempts_and_names_the_best_and_latest_score_and_an_open_attempt(
        self, signed_in_client, ready, queue
    ):
        graded(ready, 1, 16)
        graded(ready, 2, 10)
        signed_in_client.post(attempts_url(ready))  # attempt 3, preparing

        body = signed_in_client.get(f"/api/lessons/{ready.id}").json()

        assert body["attempts_count"] == 2 and body["has_open_attempt"] is True
        assert body["best_score"] == {"awarded": 16, "available": 20}
        assert body["latest_score"] == {"awarded": 10, "available": 20} == body["test_score"]
        assert body["test_status"] == "generating"

    def test_a_lesson_never_tested_has_none_of_it(self, signed_in_client, ready):
        body = signed_in_client.get(f"/api/lessons/{ready.id}").json()

        assert (body["attempts_count"], body["best_score"], body["latest_score"], body["has_open_attempt"]) == (
            0, None, None, False,
        )  # fmt: skip
        assert body["test_status"] == "not_started"

    def test_two_equal_best_scores_name_the_earlier(self, signed_in_client, ready):
        graded(ready, 1, 14)
        graded(ready, 2, 14)

        assert signed_in_client.get(f"/api/lessons/{ready.id}").json()["best_score"] == {"awarded": 14, "available": 20}


class TestTheOldSingleCall:
    def test_the_first_attempt_can_still_be_started_and_submitted_in_one_call(self, signed_in_client, ready, queue):
        response = signed_in_client.post(
            f"/api/lessons/{ready.id}/test/submissions", {"answers": ALL_RIGHT}, format="json"
        )

        body = response.json()
        assert response.status_code == 202 and body["status"] == "graded" and body["run_id"] is None
        assert body["awarded"] == 20 and body["attempt_no"] == 1

    def test_once_there_is_an_attempt_it_is_refused_naming_it(self, signed_in_client, ready, queue):
        attempt = first_attempt(signed_in_client, ready)["attempt_id"]

        response = signed_in_client.post(f"/api/lessons/{ready.id}/test/submissions", {"answers": {}}, format="json")

        assert (response.status_code, response.json()["code"]) == (409, "already_submitted")
        assert response.json()["submission_id"] == attempt


def test_the_gate_helper_is_a_counting_gate():
    assert SharedCountingGate.authorized == [] and RefusingGate is not None
