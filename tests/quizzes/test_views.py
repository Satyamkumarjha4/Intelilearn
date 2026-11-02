"""Unit under test: the quick quiz endpoints (`/api/quick-quizzes...`), as the browser uses them.

Why: this is where a quiz meets the network. A creation that is answered twice must be one quiz and one authorization; a
rule the wizard hides (short answers in a five-question quiz) must still be refused when the request is made by hand; an
answer key, a calibration band or another learner's quiz must never reach a response; and the costly calls must be rate
limited.

Use cases:
- topic-traits: the judge's answer shaped for the wizard, never an error, rate limited, and it needs a topic
- make: a topic quiz and a quiz from lessons are 202 with ids; the rules of the request are 400s naming the field; a
  lesson that is not yours is a 404; a repeat with the same Idempotency-Key is the first answer and asks the gate once;
  a refused action creates nothing; it is rate limited; a model that is not bound is a 503
- the list is paged, the learner's own, with the latest score; the detail has the stage, the level, the sources, the
  attempts and their trend, and whether a lesson can be made
- calibration: one question at a time with no band, answer or hint; an answer returns the next or the level; a stale
  answer is a 409
- attempts: a retake is a 202 with a run id (a repeat is the same attempt), the answers lock their questions, submit
  grades an objective attempt in the same request and queues grading for written answers, and a sealed attempt is a 409
- the result of a quiz from lessons carries, for each weak concept, the page of the lesson that teaches it, and marks a
  deleted lesson
- the result carries the score card and the advice; no response carries an answer key, whatever the kind of question
- another learner's quiz and attempt are a 404, and a signed-out request is a 401
- delete removes the quiz and its data
- create-lesson makes a lesson from a topic quiz result, and refuses a quiz from lessons and an attempt that is not
  graded
"""

import pytest
from rest_framework.throttling import SimpleRateThrottle
from support.gates import SharedCountingGate
from support.question_data import make_question

from graph.questions.traits import TopicTraits
from lessons.models import GraphRun, Lesson
from quizzes.models import QuickQuiz, QuickQuizAttempt
from quizzes.services import QuickQuizService
from quizzes.stages import QuizStage
from quizzes.views import QuizListCreateView, TopicTraitsView

pytestmark = pytest.mark.django_db

#: all a learner is shown of a question while the attempt is open: anything else (the answer, the marking scheme, the
#: concept, the difficulty, the lesson it is about) is a leak
SHOWN = {"id", "type", "question", "marks", "options", "unit", "decimal_precision", "language", "starter_code"}
BODY = {
    "source": {"type": "topic", "topic": "Binary search"}, "num_questions": 10, "types": ["mcq"],
    "level": {"mode": "self_rating", "rating": 3},
}  # fmt: skip


@pytest.fixture(autouse=True)
def gate(settings):
    SharedCountingGate.reset()
    settings.ACTION_GATE = "support.gates.SharedCountingGate"
    return SharedCountingGate


@pytest.fixture(autouse=True)
def fake_judge(monkeypatch, traits_for):
    """The topic judge is a fake, so no test reaches a model."""
    judge = traits_for(TopicTraits(quantitative=True, programming=False))
    monkeypatch.setattr(TopicTraitsView, "traits_factory", staticmethod(lambda: judge))
    monkeypatch.setattr(QuizListCreateView, "service_factory", staticmethod(lambda: QuickQuizService(traits=judge)))
    return judge


def post(client, body=None, **headers):
    return client.post("/api/quick-quizzes", BODY | (body or {}), format="json", **headers)


class TestTopicTraits:
    def test_the_answer_is_shaped_for_the_wizard(self, signed_in_client):
        response = signed_in_client.post("/api/quick-quizzes/topic-traits", {"topic": "Algebra"}, format="json")

        assert response.status_code == 200
        assert response.json() == {"numerical": True, "code": False, "source": "model"}

    def test_a_judge_that_fails_is_still_a_200_with_the_fallback(self, signed_in_client, monkeypatch, traits_for):
        broken = traits_for(None)
        monkeypatch.setattr(TopicTraitsView, "traits_factory", staticmethod(lambda: broken))

        response = signed_in_client.post("/api/quick-quizzes/topic-traits", {"topic": "Algebra"}, format="json")

        assert response.status_code == 200 and response.json() == {
            "numerical": True,
            "code": False,
            "source": "fallback",
        }

    @pytest.mark.parametrize("body", [{}, {"topic": ""}, {"topic": "x"}, {"topic": "Algebra", "num_questions": 12}])
    def test_a_bad_request_is_a_400(self, signed_in_client, body):
        assert signed_in_client.post("/api/quick-quizzes/topic-traits", body, format="json").status_code == 400

    def test_it_is_rate_limited(self, signed_in_client, monkeypatch):
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "topic_traits", "2/min")

        codes = [
            signed_in_client.post("/api/quick-quizzes/topic-traits", {"topic": "Algebra"}, format="json").status_code
            for _ in range(3)
        ]

        assert codes == [200, 200, 429]

    def test_it_needs_a_signed_in_learner(self, api_client):
        assert (
            api_client.post("/api/quick-quizzes/topic-traits", {"topic": "Algebra"}, format="json").status_code == 401
        )


class TestMaking:
    def test_a_topic_quiz_is_202_with_ids_and_a_queued_run(self, signed_in_client, queue, bound_registry, gate):
        response = post(signed_in_client)

        assert response.status_code == 202
        quiz = QuickQuiz.objects.get(pk=response.json()["quiz_id"])
        assert GraphRun.objects.get(pk=response.json()["run_id"]).quick_quiz_id == quiz.pk
        assert str(queue.runs[0].pk) == response.json()["run_id"] and gate.authorized[0].action == "quiz.create"

    def test_a_quiz_from_lessons_is_202(self, signed_in_client, queue, bound_registry, make_ready_lesson):
        a, b = make_ready_lesson("A", "beginner"), make_ready_lesson("B", "expert")
        body = {"source": {"type": "lessons", "lesson_ids": [str(a.pk), str(b.pk)]}}

        response = post(signed_in_client, body)

        assert response.status_code == 202
        assert QuickQuiz.objects.get(pk=response.json()["quiz_id"]).sources.count() == 2

    @pytest.mark.parametrize(
        ("body", "field"),
        [
            ({"num_questions": 12}, "num_questions"),
            ({"num_questions": "ten"}, "num_questions"),
            ({"num_questions": 5, "types": ["mcq", "short_answer"]}, "types"),
            ({"types": ["essay"]}, "types"),
            ({"types": []}, "types"),
            ({"types": "mcq"}, "types"),
            ({"level": {"mode": "existing_score"}}, "level"),
            ({"level": {"mode": "self_rating", "rating": 9}}, "level"),
            ({"level": {"mode": "magic"}}, "level.mode"),
            ({"source": {"type": "topic"}}, "source.topic"),
            ({"source": {"type": "lessons"}}, "source.lesson_ids"),
            ({"source": {"type": "topic", "topic": "x"}}, "source.topic"),
            ({"source": {"type": "topic", "topic": "Algebra", "lesson_ids": []}}, "source.lesson_ids"),
        ],
    )
    def test_a_rule_of_the_request_is_a_400_naming_the_field_that_creates_nothing(
        self, signed_in_client, queue, bound_registry, gate, body, field
    ):
        response = post(signed_in_client, body)

        assert response.status_code == 400 and response.json()["code"] == "invalid"
        shown = response.json()["fields"]
        assert field.split(".")[0] in shown
        assert QuickQuiz.objects.count() == 0 and queue.runs == [] and gate.authorized == []

    def test_a_lesson_that_is_not_yours_is_a_404(
        self, signed_in_client, other_user, make_ready_lesson, queue, bound_registry
    ):
        theirs = make_ready_lesson("Theirs", owner=other_user)

        response = post(signed_in_client, {"source": {"type": "lessons", "lesson_ids": [str(theirs.pk)]}})

        assert response.status_code == 404 and QuickQuiz.objects.count() == 0

    def test_a_lesson_that_is_only_sheets_is_a_400_with_the_reason(
        self, signed_in_client, make_ready_lesson, queue, bound_registry
    ):
        sheets = make_ready_lesson("Sheets", intent="sheets")

        response = post(signed_in_client, {"source": {"type": "lessons", "lesson_ids": [str(sheets.pk)]}})

        assert response.status_code == 400 and response.json()["code"] == "source_not_usable"
        assert "study sheets only" in response.json()["detail"] and "source" in response.json()["fields"]

    def test_more_than_ten_lessons_are_a_400(self, signed_in_client, make_ready_lesson, queue, bound_registry):
        ids = [str(make_ready_lesson(f"L{n}").pk) for n in range(11)]

        response = post(signed_in_client, {"num_questions": 30, "source": {"type": "lessons", "lesson_ids": ids}})

        assert response.status_code == 400 and "at most 10" in str(response.json()["fields"]["source"])

    def test_a_count_below_the_lessons_is_a_400(self, signed_in_client, make_ready_lesson, queue, bound_registry):
        ids = [str(make_ready_lesson(f"L{n}").pk) for n in range(6)]

        response = post(signed_in_client, {"num_questions": 5, "source": {"type": "lessons", "lesson_ids": ids}})

        assert response.status_code == 400 and "num_questions" in response.json()["fields"]

    def test_an_unbound_model_is_a_503(self, signed_in_client, queue, db):
        from llm_registry.node_configs import NodeConfigSync

        NodeConfigSync().ensure()

        response = post(signed_in_client)

        assert response.status_code == 503 and response.json()["code"] == "llm_not_configured"

    def test_a_refused_action_creates_nothing(self, signed_in_client, queue, bound_registry, settings):
        settings.ACTION_GATE = "support.gates.RefusingSharedGate"

        response = post(signed_in_client)

        assert response.status_code == 403 and response.json()["code"] == "test_refused"
        assert QuickQuiz.objects.count() == 0 and queue.runs == []

    def test_the_idempotency_key_makes_a_repeat_the_first_answer(self, signed_in_client, queue, bound_registry, gate):
        first = post(signed_in_client, HTTP_IDEMPOTENCY_KEY="k1")
        second = post(signed_in_client, HTTP_IDEMPOTENCY_KEY="k1")

        assert first.json() == second.json() and second["Idempotent-Replayed"] == "true"
        assert QuickQuiz.objects.count() == 1 and len(gate.authorized) == 1

    def test_it_is_rate_limited(self, signed_in_client, queue, bound_registry, monkeypatch):
        monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "quiz_create", "2/hour")

        codes = [post(signed_in_client).status_code for _ in range(3)]

        assert codes == [202, 202, 429]

    def test_a_signed_out_request_is_a_401(self, api_client):
        assert api_client.post("/api/quick-quizzes", BODY, format="json").status_code == 401


class TestReading:
    def test_the_list_is_the_learners_own_with_the_latest_score(
        self, signed_in_client, make_quiz, make_attempt, other_user
    ):
        mine = make_quiz(topic="Mine")
        make_attempt(mine, status="graded", awarded=3, available=4)
        make_attempt(mine, status="graded", awarded=2, available=4)
        make_quiz(topic="Theirs", owner=other_user)

        body = signed_in_client.get("/api/quick-quizzes").json()

        (row,) = body["results"]
        assert (row["topic"], row["attempts_count"], row["latest_score"], row["best_score"]) == ("Mine", 2, 50, 75)
        assert row["num_questions"] == 10 and row["stage"] == "ready"

    def test_the_detail_has_the_stage_level_sources_and_attempts(self, signed_in_client, make_quiz, make_attempt):
        quiz = make_quiz(assessment={"level": "foundation", "source": "self_rating", "level_scheme": 2})
        make_attempt(quiz, status="graded", awarded=1, available=2, result={"score": {}}, band="normal")
        make_attempt(quiz, status="in_progress")

        body = signed_in_client.get(f"/api/quick-quizzes/{quiz.pk}").json()

        assert (body["stage"], body["level"], body["level_source"]) == ("ready", "foundation", "self_rating")
        assert body["config"] == {
            "num_questions": 10,
            "types": ["mcq"],
            "level_mode": "self_rating",
            "self_rating": 3.0,
        }
        assert [a["attempt_no"] for a in body["attempts"]] == [1, 2] and body["open_attempt"]["attempt_no"] == 2
        assert body["trend"]["series"][0]["percent"] == 50 and body["can_create_lesson"] is True

    def test_another_learners_quiz_is_a_404_on_every_route(self, signed_in_client, make_quiz, make_attempt, other_user):
        theirs = make_quiz(owner=other_user, topic="Theirs")
        attempt = make_attempt(theirs, status="in_progress")
        base = f"/api/quick-quizzes/{theirs.pk}"

        gets = [
            signed_in_client.get(url).status_code
            for url in (base, f"{base}/calibration", f"{base}/attempts", f"{base}/attempts/{attempt.pk}")
        ]
        posts = [
            signed_in_client.post(url, {}, format="json").status_code
            for url in (
                f"{base}/attempts",
                f"{base}/calibration/answer",
                f"{base}/create-lesson",
                f"{base}/attempts/{attempt.pk}/submit",
            )
        ]
        put = signed_in_client.put(f"{base}/attempts/{attempt.pk}/answers/t1", {"answer": 1}, format="json").status_code

        assert set(gets + posts + [put, signed_in_client.delete(base).status_code]) == {404}

    def test_an_id_that_is_not_an_id_is_a_404(self, signed_in_client):
        assert signed_in_client.get("/api/quick-quizzes/not-a-uuid").status_code == 404


class TestCalibration:
    @pytest.fixture
    def walking(self, make_quiz):
        from support.quiz_data import make_questions

        return make_quiz(stage=QuizStage.AWAITING_CALIBRATION, calibration={"pool": make_questions(), "walk": []})

    def test_one_question_with_no_band_answer_or_hint(self, signed_in_client, walking):
        body = signed_in_client.get(f"/api/quick-quizzes/{walking.pk}/calibration").json()

        assert body["done"] is False and set(body) == {"done", "step", "total", "question"}
        assert set(body["question"]) == {"id", "question", "options"}

    def test_an_answer_returns_the_next_question_and_a_stale_one_is_a_409(self, signed_in_client, walking, queue):
        url = f"/api/quick-quizzes/{walking.pk}/calibration/answer"

        first = signed_in_client.post(url, {"question_id": "q5", "answer": 0}, format="json").json()
        stale = signed_in_client.post(url, {"question_id": "q5", "answer": 1}, format="json")

        assert first["question"]["id"] == "q7" and first["step"] == 2
        assert stale.status_code == 409 and stale.json()["code"] == "not_current"

    def test_the_fifth_answer_returns_the_level_and_queues_the_resume(self, signed_in_client, walking, queue):
        url = f"/api/quick-quizzes/{walking.pk}/calibration/answer"
        for _ in range(5):
            question = signed_in_client.get(f"/api/quick-quizzes/{walking.pk}/calibration").json()["question"]
            body = signed_in_client.post(url, {"question_id": question["id"], "answer": 0}, format="json").json()

        assert body == {"done": True, "level": "expert"} and len(queue.runs) == 1

    def test_a_quiz_that_is_not_waiting_is_a_409(self, signed_in_client, quiz):
        assert signed_in_client.get(f"/api/quick-quizzes/{quiz.pk}/calibration").status_code == 409

    @pytest.mark.parametrize("body", [{}, {"question_id": "q5"}, {"answer": 0}])
    def test_a_bad_answer_is_a_400(self, signed_in_client, walking, body):
        assert (
            signed_in_client.post(
                f"/api/quick-quizzes/{walking.pk}/calibration/answer", body, format="json"
            ).status_code
            == 400
        )


QUESTIONS = [
    make_question("mcq", 1, "easy"),
    make_question("msq", 2, "basic"),
    make_question("numerical", 3, "standard"),
]


def right(question):
    return {
        "mcq": question.get("correct_index"),
        "msq": question.get("correct_indices"),
        "numerical": question.get("answer"),
    }[question["type"]]


@pytest.fixture
def taking(make_quiz, make_attempt):
    quiz = make_quiz()
    return quiz, make_attempt(quiz, status="in_progress", questions=QUESTIONS)


def attempt_url(quiz, attempt, suffix=""):
    return f"/api/quick-quizzes/{quiz.pk}/attempts/{attempt.pk}{suffix}"


class TestAttempts:
    def test_an_open_attempt_is_read_with_its_questions_and_no_keys(self, signed_in_client, taking):
        quiz, attempt = taking

        body = signed_in_client.get(attempt_url(quiz, attempt)).json()

        assert [q["id"] for q in body["questions"]] == ["t1", "t2", "t3"] and body["total_marks"] == 5
        assert all(set(q) <= SHOWN for q in body["questions"])

    @pytest.mark.parametrize("kind", ["mcq", "msq", "numerical", "short_answer", "long_answer"])
    def test_no_kind_of_question_leaks_its_key_while_open_and_all_are_shown_after(
        self, signed_in_client, make_quiz, make_attempt, kind
    ):
        quiz = make_quiz()
        attempt = make_attempt(
            quiz, status="in_progress", questions=[make_question(kind, 1, "difficult") | {"source": "a-lesson"}]
        )

        open_body = signed_in_client.get(attempt_url(quiz, attempt)).json()

        assert all(set(q) <= SHOWN for q in open_body["questions"]) and open_body["questions"]
        assert open_body["result"] is None

    def test_an_answer_locks_its_question(self, signed_in_client, taking):
        quiz, attempt = taking
        url = attempt_url(quiz, attempt, "/answers/t1")

        saved = signed_in_client.put(url, {"answer": 1}, format="json")
        again = signed_in_client.put(url, {"answer": 0}, format="json")

        assert saved.status_code == 200 and saved.json()["locked"] is True
        assert again.status_code == 409 and again.json()["code"] == "locked"

    @pytest.mark.parametrize(
        ("question", "answer", "status"), [("t9", 1, 400), ("t1", {"a": 1}, 400), ("t1", [1] * 20, 400)]
    )
    def test_a_bad_answer_is_a_400(self, signed_in_client, taking, question, answer, status):
        quiz, attempt = taking

        response = signed_in_client.put(
            attempt_url(quiz, attempt, f"/answers/{question}"), {"answer": answer}, format="json"
        )

        assert response.status_code == status

    def test_submitting_an_objective_attempt_grades_it_in_the_request(self, signed_in_client, taking, queue):
        quiz, attempt = taking
        answers = {q["id"]: right(q) for q in QUESTIONS}

        response = signed_in_client.post(attempt_url(quiz, attempt, "/submit"), {"answers": answers}, format="json")

        body = response.json()
        assert response.status_code == 200 and body["status"] == "graded" and body["run_id"] is None
        assert body["awarded"] == body["available"] == 5 and body["band"] == "excellent" and queue.runs == []

    def test_written_answers_queue_grading_and_say_so(self, signed_in_client, make_quiz, make_attempt, queue):
        quiz = make_quiz()
        attempt = make_attempt(quiz, status="in_progress", questions=[make_question("short_answer", 1, "easy")])

        response = signed_in_client.post(
            attempt_url(quiz, attempt, "/submit"), {"answers": {"t1": "Halve it."}}, format="json"
        )

        assert response.status_code == 202 and response.json()["status"] == "grading"
        run = GraphRun.objects.get(pk=response.json()["run_id"])
        assert (run.graph, run.quick_quiz_id) == ("grade_quiz", quiz.pk) and queue.runs == [run]

    def test_a_sealed_attempt_is_a_409(self, signed_in_client, taking):
        quiz, attempt = taking
        signed_in_client.post(attempt_url(quiz, attempt, "/submit"), {}, format="json")

        again = signed_in_client.post(attempt_url(quiz, attempt, "/submit"), {}, format="json")
        late = signed_in_client.put(attempt_url(quiz, attempt, "/answers/t1"), {"answer": 1}, format="json")

        assert (again.status_code, again.json()["code"]) == (409, "attempt_sealed") and late.status_code == 409

    def test_the_result_has_the_card_the_questions_and_the_advice(self, signed_in_client, taking):
        quiz, attempt = taking
        signed_in_client.post(attempt_url(quiz, attempt, "/submit"), {"answers": {"t1": 0}}, format="json")

        body = signed_in_client.get(attempt_url(quiz, attempt)).json()

        assert body["status"] == "graded" and body["result"]["score"]["available"] == 5
        assert len(body["questions"]) == 3 and body["recommendations"]["kind"] == "topic"
        assert all(row["solution"] for row in body["result"]["questions"])  # the solutions are shown once it is over

    def test_a_quiz_from_lessons_links_each_weak_concept_to_a_page(
        self, signed_in_client, make_quiz, make_attempt, make_ready_lesson
    ):
        from quizzes.models import QuickQuizSource

        quiz = make_quiz(source_type="lessons", topic="Mixed")
        lesson = make_ready_lesson("Binary search")
        QuickQuizSource.objects.create(
            quiz=quiz, lesson=lesson, lesson_ref=lesson.pk, title="Binary search", level="foundation", share=2
        )
        row = {
            "id": "t1", "type": "mcq", "concept": "The loop invariant", "marks": 2, "awarded": 0, "correct": False,
            "graded_by": "auto", "feedback": "", "solution": {"correct_index": 1},
        }  # fmt: skip
        attempt = make_attempt(
            quiz, status="graded",
            questions=[make_question("mcq", 1, "easy", concept="The loop invariant") | {"source": str(lesson.pk)}],
            result={"complete": True, "score": {"awarded": 0, "available": 2, "percent": 0}, "questions": [row],
                    "topics_to_revisit": ["The loop invariant"]},
        )  # fmt: skip

        body = signed_in_client.get(attempt_url(quiz, attempt)).json()

        (advice,) = body["recommendations"]["lessons"]
        assert advice["lesson_id"] == str(lesson.pk) and advice["deleted"] is False
        assert advice["links"] == [
            {"concept": "The loop invariant", "page": "core", "heading": "The loop invariant", "marks_lost": 2}
        ]
        lesson.delete()
        (gone,) = signed_in_client.get(attempt_url(quiz, attempt)).json()["recommendations"]["lessons"]
        assert gone["lesson_id"] is None and gone["deleted"] is True and gone["links"][0]["page"] == ""

    def test_the_history_lists_attempts_and_a_trend_of_this_quiz_only(self, signed_in_client, make_quiz, make_attempt):
        quiz, other = make_quiz(), make_quiz(topic="Other")
        make_attempt(quiz, status="graded", awarded=2, available=4)
        make_attempt(quiz, status="graded", awarded=3, available=4)
        make_attempt(other, status="graded", awarded=4, available=4)

        body = signed_in_client.get(f"/api/quick-quizzes/{quiz.pk}/attempts").json()

        assert [a["percent"] for a in body["attempts"]] == [50, 75]
        assert [p["delta_previous"] for p in body["trend"]["series"]] == [None, 25]

    def test_a_retake_is_a_202_with_a_run_and_a_repeat_is_the_same_attempt(
        self, signed_in_client, make_quiz, make_attempt, queue, bound_registry, gate
    ):
        quiz = make_quiz()
        make_attempt(quiz, status="graded", awarded=1, available=2)

        first = signed_in_client.post(f"/api/quick-quizzes/{quiz.pk}/attempts")
        again = signed_in_client.post(f"/api/quick-quizzes/{quiz.pk}/attempts")

        assert first.status_code == again.status_code == 202 and first.json()["questions"] == []
        assert (
            first.json()["attempt_id"] == again.json()["attempt_id"]
            and first.json()["run_id"] == again.json()["run_id"]
        )
        assert (
            first.json()["attempt_no"] == 2 and len(gate.authorized) == 1 and gate.authorized[0].action == "quiz.retake"
        )

    def test_an_attempt_that_is_open_is_resumed_with_a_200(self, signed_in_client, taking):
        quiz, attempt = taking

        response = signed_in_client.post(f"/api/quick-quizzes/{quiz.pk}/attempts")

        assert response.status_code == 200 and response.json()["attempt_id"] == str(attempt.pk)
        assert len(response.json()["questions"]) == 3

    def test_a_retake_of_a_quiz_that_is_not_ready_is_a_409(self, signed_in_client, make_quiz):
        quiz = make_quiz(stage=QuizStage.PREPARING)

        assert signed_in_client.post(f"/api/quick-quizzes/{quiz.pk}/attempts").status_code == 409

    def test_a_failed_grading_can_be_graded_again(self, signed_in_client, make_quiz, make_attempt, queue):
        quiz = make_quiz()
        attempt = make_attempt(quiz, status="failed", questions=[make_question("short_answer", 1)], answers={"t1": "x"})

        response = signed_in_client.post(attempt_url(quiz, attempt, "/regrade"))

        assert response.status_code == 202 and QuickQuizAttempt.objects.get(pk=attempt.pk).status == "grading"
        assert signed_in_client.post(attempt_url(quiz, attempt, "/regrade")).status_code == 409


class TestDeleting:
    def test_the_quiz_and_its_attempts_are_gone(self, signed_in_client, quiz, make_attempt, monkeypatch):
        from quizzes.erasure import QuizErasure

        monkeypatch.setattr(QuizErasure, "erase", lambda self, q: None)
        make_attempt(quiz, status="graded")

        response = signed_in_client.delete(f"/api/quick-quizzes/{quiz.pk}")

        assert response.status_code == 204 and not QuickQuiz.objects.exists() and not QuickQuizAttempt.objects.exists()


class TestCreateLesson:
    @pytest.fixture
    def finished(self, quiz, make_attempt):
        QuickQuiz.objects.filter(pk=quiz.pk).update(assessment={"level": "foundation", "level_scheme": 2})
        card = {
            "complete": True,
            "score": {"awarded": 1, "available": 4, "percent": 25},
            "questions": [],
            "topics_to_revisit": ["Loops"],
        }
        return quiz, make_attempt(quiz, status="graded", result=card, band="normal", awarded=1, available=4)

    def test_a_topic_quiz_becomes_a_lesson_with_the_result_as_its_origin(
        self, signed_in_client, finished, queue, bound_registry, gate
    ):
        quiz, attempt = finished

        response = signed_in_client.post(
            f"/api/quick-quizzes/{quiz.pk}/create-lesson", {"attempt_id": str(attempt.pk)}, format="json"
        )

        assert response.status_code == 202
        lesson = Lesson.objects.get(pk=response.json()["lesson_id"])
        assert (lesson.entry, lesson.origin, lesson.topic) == ("quiz_result", "quiz_result", "Binary search")
        assert lesson.recommended_from == {
            "quiz_id": str(quiz.pk),
            "attempt_id": str(attempt.pk),
            "topic": "Binary search",
        }
        assert gate.authorized[-1].action == "lesson.create" and gate.authorized[-1].size["origin"] == "quiz_result"
        assert gate.authorized[-1].size["covers"] == "all"

    def test_the_same_lesson_is_made_by_post_lessons_with_the_quiz_result_entry(
        self, signed_in_client, finished, queue, bound_registry
    ):
        quiz, attempt = finished

        response = signed_in_client.post(
            "/api/lessons",
            {"topic": "ignored", "entry": "quiz_result", "quiz_attempt_id": str(attempt.pk)},
            format="json",
        )

        assert response.status_code == 202
        lesson = Lesson.objects.get(pk=response.json()["lesson_id"])
        assert (lesson.entry, lesson.origin, lesson.topic) == ("quiz_result", "quiz_result", "Binary search")

    @pytest.mark.parametrize(
        "body",
        [
            {"entry": "quiz_result"},
            {"entry": "quiz_result", "quiz_attempt_id": "00000000-0000-0000-0000-000000000000"},
            {"quiz_attempt_id": "00000000-0000-0000-0000-000000000000"},
            {"origin": "quiz_result"},
        ],
    )
    def test_a_lesson_cannot_claim_a_quiz_result_it_does_not_have(self, signed_in_client, queue, bound_registry, body):
        response = signed_in_client.post("/api/lessons", {"topic": "Algebra"} | body, format="json")

        assert response.status_code == 400 and Lesson.objects.count() == 0 and queue.runs == []

    def test_a_quiz_from_lessons_is_refused_and_points_at_the_lessons(
        self, signed_in_client, make_quiz, make_attempt, queue, bound_registry
    ):
        mixed = make_quiz(source_type="lessons", topic="Mixed")
        attempt = make_attempt(
            mixed, status="graded", result={"score": {"awarded": 1, "available": 2}, "questions": []}
        )

        response = signed_in_client.post(
            f"/api/quick-quizzes/{mixed.pk}/create-lesson", {"attempt_id": str(attempt.pk)}, format="json"
        )

        assert response.status_code == 400 and response.json()["code"] == "not_a_topic_quiz"

    def test_an_attempt_that_is_not_graded_or_not_this_quizs_is_a_404(
        self, signed_in_client, finished, make_quiz, make_attempt, queue, bound_registry
    ):
        quiz, _ = finished
        open_attempt = make_attempt(quiz, status="in_progress")
        elsewhere = make_attempt(make_quiz(topic="Other"), status="graded", result={"score": {}, "questions": []})

        for attempt in (open_attempt, elsewhere):
            response = signed_in_client.post(
                f"/api/quick-quizzes/{quiz.pk}/create-lesson", {"attempt_id": str(attempt.pk)}, format="json"
            )
            assert response.status_code == 404

    def test_a_beginner_result_needs_the_prerequisite_planner(self, signed_in_client, finished, queue, bound_registry):
        from llm_registry.models import NodeModelBinding

        quiz, attempt = finished
        QuickQuiz.objects.filter(pk=quiz.pk).update(assessment={"level": "beginner", "level_scheme": 2})
        QuickQuizAttempt.objects.filter(pk=attempt.pk).update(band="fail")
        NodeModelBinding.objects.filter(node__node_key="prerequisites.plan").delete()

        response = signed_in_client.post(
            f"/api/quick-quizzes/{quiz.pk}/create-lesson", {"attempt_id": str(attempt.pk)}, format="json"
        )

        assert response.status_code == 503 and Lesson.objects.count() == 0
