"""Unit under test: `lessons.attempts.AttemptService`, a learner's attempts at a lesson's test.

Why: this is where a learner's result is made, kept and protected. Attempt 1 is part of the lesson and must start with
no cost and no wait; a retake costs a generation, so it has to ask the gate first, create nothing when refused, return
the open attempt instead of drawing a second set, and leave no row behind when it fails. Once an attempt is over it must
never change. A lesson attempt is objective, so submitting must grade it completely in the same request.

Use cases:
- the first attempt starts at once from the questions the lesson was built with (its first set on the record; a
  legacy lesson's test was moved there by migration 0019), is never metered, and is returned again by a repeated start
- a retake is created `generating`, asks the gate for test.retake once with its size, queues the question_bank run with
  the authorization on it, and is returned again by a repeated start without asking again
- a refused retake creates no attempt and queues nothing
- a start for a lesson that is not ready, or is a mastery lesson, is refused
- reading the test shows the open attempt's questions without keys and the answers saved so far, never starts anything,
  and says which attempt a start would make
- saving an answer locks the question; a second save, a save to a sealed attempt, a preparing attempt, an unknown
  question or a bad answer is refused and changes nothing; a blank answer locks too
- submit seals the attempt and grades it in full: score, band and the offer in the same call, no run; missing answers
  are blank and score 0; an attempt of blank answers is stored, scores 0 and is flagged; the answers sent with the
  submit fill only questions that are not locked
- a sealed attempt cannot be submitted again, and nothing but `seal` writes its answers or questions
- a legacy attempt with open-ended questions is marked as far as it can be and queued for grading
- the history lists every attempt with its trend; the latest attempt is the one with the highest number
"""

import ast
import pathlib

import pytest
from support.gates import CountingGate, RefusingGate
from support.lesson_data import make_blueprint_test, make_final_test, make_plan
from support.question_data import make_question

import lessons
from lessons.attempts import AttemptService
from lessons.errors import (
    AttemptSealed,
    InvalidAnswers,
    QuestionLocked,
    SubmissionNotFound,
    WrongStage,
)
from lessons.metering import ActionRefused
from lessons.models import GraphRun, Stage, TestSubmission

pytestmark = pytest.mark.django_db

TEST = make_blueprint_test()
QUESTIONS = TEST["questions"]
MARKS = {q["id"]: q["marks"] for q in QUESTIONS}
SECRETS = ("correct_index", "correct_indices", "answer", "answer_expr", "tolerance", "concept", "difficulty")


def ready(make_lesson, **fields):
    defaults = {"stage": Stage.READY, "final_test": TEST, "plan": make_plan(), "settings_snapshot": {}}
    return make_lesson(**defaults | fields)


def right(question: dict):
    """An answer that earns full marks."""
    field = {"mcq": "correct_index", "msq": "correct_indices", "numerical": "answer"}[question["type"]]
    return question[field]


def all_right() -> dict:
    return {q["id"]: right(q) for q in QUESTIONS}


def graded_attempt(lesson, number=1, awarded=14, available=20, **fields):
    return TestSubmission.objects.create(
        lesson=lesson, attempt_no=number, status="graded", awarded=awarded, available=available, questions=QUESTIONS,
        result={"complete": True, "score": {"awarded": awarded, "available": available, "percent": 0}, "questions": []},
        **fields,
    )  # fmt: skip


def without_row(question: dict) -> dict:
    """The question as it was written: the first set carries the id of its row, the test it came from did not."""
    return {k: v for k, v in question.items() if k != "question_id"}


class TestStartTheFirstAttempt:
    def test_it_starts_at_once_from_the_questions_the_lesson_was_built_with(self, make_lesson, queue):
        lesson = ready(make_lesson)

        started = AttemptService(queue=queue).start(lesson)

        assert started.created is True and started.run is None and queue.runs == []
        attempt = started.attempt
        assert (attempt.attempt_no, attempt.status) == (1, "in_progress")
        assert [without_row(q) for q in attempt.questions] == QUESTIONS and all(
            q["question_id"] for q in attempt.questions
        )
        assert attempt.answers == {} and attempt.submitted_at is None

    def test_it_is_never_metered(self, make_lesson, queue):
        gate = CountingGate()

        AttemptService(queue=queue, gate=gate).start(ready(make_lesson))

        assert gate.authorized == []

    def test_a_repeated_start_returns_the_open_attempt(self, make_lesson, queue):
        lesson = ready(make_lesson)
        service = AttemptService(queue=queue)
        first = service.start(lesson)

        again = service.start(lesson)

        assert again.created is False and again.attempt.pk == first.attempt.pk
        assert TestSubmission.objects.filter(lesson=lesson).count() == 1

    def test_a_lesson_made_before_the_fixed_test_snapshots_its_old_test(self, make_lesson, queue):
        old = make_final_test()
        lesson = ready(make_lesson, final_test=old, plan=None)

        attempt = AttemptService(queue=queue).start(lesson).attempt

        assert [without_row(q) for q in attempt.questions] == old["questions"] and len(old["questions"]) == 10

    @pytest.mark.parametrize(
        "fields",
        [{"stage": Stage.GENERATING_LESSON}, {"route": "mastery"}, {"final_test": None}, {"final_test": {}}],
    )
    def test_a_lesson_that_is_not_ready_or_has_no_test_is_refused(self, make_lesson, queue, fields):
        with pytest.raises(WrongStage):
            AttemptService(queue=queue).start(ready(make_lesson, **fields))

        assert not TestSubmission.objects.exists()


class TestStartARetake:
    def retakeable(self, make_lesson, **fields):
        lesson = ready(make_lesson, **fields)
        graded_attempt(lesson)
        return lesson

    def test_it_is_created_generating_and_the_question_bank_run_is_queued_with_its_authorization(
        self, make_lesson, queue
    ):
        lesson, gate = self.retakeable(make_lesson), CountingGate()

        started = AttemptService(queue=queue, gate=gate).start(lesson)

        attempt, run = started.attempt, started.run
        assert started.created and (attempt.attempt_no, attempt.status, attempt.questions) == (2, "generating", [])
        assert (run.graph, run.trigger) == (GraphRun.Graph.QUESTION_BANK, GraphRun.Trigger.RETAKE)
        assert run.payload["input"] == {"attempt_id": str(attempt.id)} and queue.runs == [run]
        assert run.payload["authorization"]["action"] == "test.retake"
        assert run.payload["authorization"]["completes_at"] == {"kind": "run_end", "stage": ""}

    def test_the_gate_is_asked_once_with_the_size_of_the_work(self, make_lesson, queue):
        gate = CountingGate()
        lesson = self.retakeable(make_lesson)

        started = AttemptService(queue=queue, gate=gate).start(lesson, "key-1")

        (context,) = gate.asked("test.retake")
        assert context.size == {"question_count": 10, "attempt_no": 2} and context.resume is False
        assert context.subject_id == started.attempt.id and context.key.endswith(":key-1")

    def test_a_repeated_start_while_it_waits_returns_the_attempt_and_its_run_and_asks_nothing(self, make_lesson, queue):
        gate = CountingGate()
        service = AttemptService(queue=queue, gate=gate)
        lesson = self.retakeable(make_lesson)
        first = service.start(lesson)

        again = service.start(lesson)

        assert again.created is False and again.attempt.pk == first.attempt.pk and again.run.pk == first.run.pk
        assert len(gate.authorized) == 1 and len(queue.runs) == 1

    def test_a_refusal_creates_no_attempt_and_queues_nothing(self, make_lesson, queue):
        gate = RefusingGate()
        lesson = self.retakeable(make_lesson)

        with pytest.raises(ActionRefused):
            AttemptService(queue=queue, gate=gate).start(lesson)

        assert TestSubmission.objects.filter(lesson=lesson).count() == 1
        assert not GraphRun.objects.exists() and queue.runs == []

    def test_the_authorization_is_released_when_the_rows_could_not_be_created(self, make_lesson, queue):
        gate = CountingGate()
        lesson = self.retakeable(make_lesson)
        TestSubmission.objects.filter(lesson=lesson).update(attempt_no=1)

        class Clashing(AttemptService):
            def _begin_retake(self, lesson, number, key):
                return super()._begin_retake(lesson, 1, key)  # the number 1 is taken: the insert fails

        with pytest.raises(Exception, match="unique|duplicate"):
            Clashing(queue=queue, gate=gate).start(lesson)

        assert gate.settled and gate.settled[0][1] == "failed"


class TestReadTheTest:
    def test_before_any_attempt_there_are_no_questions_and_nothing_starts(self, make_lesson):
        lesson = ready(make_lesson)

        body = AttemptService().for_learner(lesson)

        assert body["questions"] == [] and body["next_attempt_no"] == 1 and body["attempt"] is None
        assert not TestSubmission.objects.exists()

    def test_an_open_attempt_shows_its_questions_without_keys_and_the_answers_saved_so_far(self, make_lesson, queue):
        lesson = ready(make_lesson)
        service = AttemptService(queue=queue)
        attempt = service.start(lesson).attempt
        service.save_answer(lesson, attempt.id, "t1", 1)

        body = service.for_learner(lesson)

        assert [q["id"] for q in body["questions"]] == [q["id"] for q in QUESTIONS]
        assert not [key for q in body["questions"] for key in SECRETS if key in q]
        assert body["answers"] == {"t1": 1} and body["total_marks"] == 20
        assert body["attempt"]["attempt_no"] == 1 and body["attempt"]["status"] == "in_progress"

    def test_a_preparing_retake_shows_no_questions(self, make_lesson, queue):
        lesson = ready(make_lesson)
        graded_attempt(lesson)
        service = AttemptService(queue=queue)
        service.start(lesson)

        body = service.for_learner(lesson)

        assert body["questions"] == [] and body["attempt"]["status"] == "generating"
        assert body["next_attempt_no"] == 3 and body["submission"]["status"] == "generating"

    def test_after_the_last_attempt_the_next_number_is_one_more(self, make_lesson):
        lesson = ready(make_lesson)
        graded_attempt(lesson)

        body = AttemptService().for_learner(lesson)

        assert body["attempt"] is None and body["next_attempt_no"] == 2 and body["submission"]["attempt_no"] == 1


class TestSaveAnAnswer:
    def started(self, make_lesson, queue):
        lesson = ready(make_lesson)
        service = AttemptService(queue=queue)
        return lesson, service, service.start(lesson).attempt

    def test_it_stores_the_answer_and_locks_the_question(self, make_lesson, queue):
        lesson, service, attempt = self.started(make_lesson, queue)

        service.save_answer(lesson, attempt.id, "t1", 1)

        assert TestSubmission.objects.get(pk=attempt.pk).answers == {"t1": 1}

    def test_a_locked_question_cannot_change(self, make_lesson, queue):
        lesson, service, attempt = self.started(make_lesson, queue)
        service.save_answer(lesson, attempt.id, "t1", 1)

        with pytest.raises(QuestionLocked):
            service.save_answer(lesson, attempt.id, "t1", 2)

        assert TestSubmission.objects.get(pk=attempt.pk).answers == {"t1": 1}

    @pytest.mark.parametrize("blank", [None, "", "   ", []])
    def test_leaving_a_question_blank_locks_it_too(self, make_lesson, queue, blank):
        lesson, service, attempt = self.started(make_lesson, queue)
        service.save_answer(lesson, attempt.id, "t2", blank)

        with pytest.raises(QuestionLocked):
            service.save_answer(lesson, attempt.id, "t2", 1)

    def test_a_multiple_select_answer_is_a_list_of_option_numbers(self, make_lesson, queue):
        lesson, service, attempt = self.started(make_lesson, queue)

        service.save_answer(lesson, attempt.id, "t4", [0, 2])

        assert TestSubmission.objects.get(pk=attempt.pk).answers == {"t4": [0, 2]}

    @pytest.mark.parametrize(
        ("question", "value", "message"),
        [("t99", 1, "Unknown question id: t99"), ("t1", ["a"], "short list"), ("t1", {"a": 1}, "number or text"),
         ("t1", True, "number or text"), ("t1", "x" * 10_001, "longer than 10000")],
    )  # fmt: skip
    def test_an_unknown_question_or_an_answer_of_the_wrong_shape_is_refused(
        self, make_lesson, queue, question, value, message
    ):
        lesson, service, attempt = self.started(make_lesson, queue)

        with pytest.raises(InvalidAnswers, match=message):
            service.save_answer(lesson, attempt.id, question, value)

        assert TestSubmission.objects.get(pk=attempt.pk).answers == {}

    def test_a_sealed_attempt_takes_no_more_answers(self, make_lesson, queue):
        lesson, service, attempt = self.started(make_lesson, queue)
        service.submit(lesson, attempt.id)

        with pytest.raises(AttemptSealed):
            service.save_answer(lesson, attempt.id, "t1", 1)

    def test_an_attempt_still_preparing_takes_no_answers(self, make_lesson, queue):
        lesson = ready(make_lesson)
        graded_attempt(lesson)
        service = AttemptService(queue=queue)
        waiting = service.start(lesson).attempt

        with pytest.raises(WrongStage, match="still being prepared"):
            service.save_answer(lesson, waiting.id, "t1", 1)

    @pytest.mark.parametrize("attempt_id", ["not-a-uuid", "00000000-0000-0000-0000-000000000000"])
    def test_an_attempt_that_does_not_exist_is_not_found(self, make_lesson, queue, attempt_id):
        with pytest.raises(SubmissionNotFound):
            AttemptService(queue=queue).save_answer(ready(make_lesson), attempt_id, "t1", 1)

    def test_another_lessons_attempt_is_not_found(self, make_lesson, queue):
        lesson, service, attempt = self.started(make_lesson, queue)

        with pytest.raises(SubmissionNotFound):
            service.save_answer(ready(make_lesson), attempt.id, "t1", 1)


class TestSubmit:
    def started(self, make_lesson, queue, **service):
        lesson = ready(make_lesson)
        svc = AttemptService(queue=queue, **service)
        return lesson, svc, svc.start(lesson).attempt

    def test_a_lesson_attempt_is_graded_in_full_in_the_same_call_with_no_run(self, make_lesson, queue):
        lesson, service, attempt = self.started(make_lesson, queue)

        attempt, run = service.submit(lesson, attempt.id, all_right())

        assert run is None and queue.runs == []
        assert attempt.status == "graded" and attempt.result["complete"] is True
        assert (attempt.awarded, attempt.available, attempt.band) == (20, 20, "excellent")
        assert attempt.submitted_at is not None and attempt.graded_at is not None and attempt.duration_s is not None
        assert attempt.followup == {"kind": "advanced", "action": "generate", "lesson_id": None}  # 100%
        assert attempt.all_blank is False

    def test_the_answers_saved_one_by_one_are_what_is_marked(self, make_lesson, queue):
        lesson, service, attempt = self.started(make_lesson, queue)
        for qid, value in all_right().items():
            service.save_answer(lesson, attempt.id, qid, value)

        sealed, _ = service.submit(lesson, attempt.id)

        assert sealed.awarded == 20 and sealed.answers == all_right()

    def test_missing_answers_are_blank_and_score_nothing(self, make_lesson, queue):
        lesson, service, attempt = self.started(make_lesson, queue)

        sealed, _ = service.submit(lesson, attempt.id, {"t1": right(QUESTIONS[0])})

        assert sealed.awarded == MARKS["t1"] and sealed.band == "fail" and sealed.all_blank is False

    def test_an_attempt_of_blank_answers_is_stored_scores_zero_and_is_flagged(self, make_lesson, queue):
        lesson, service, attempt = self.started(make_lesson, queue)

        sealed, run = service.submit(lesson, attempt.id, {"t1": None, "t2": "  ", "t4": []})

        assert run is None and sealed.status == "graded" and (sealed.awarded, sealed.available) == (0, 20)
        assert sealed.band == "fail" and sealed.all_blank is True

    def test_the_answers_sent_with_the_submit_fill_only_the_questions_that_are_not_locked(self, make_lesson, queue):
        lesson, service, attempt = self.started(make_lesson, queue)
        service.save_answer(lesson, attempt.id, "t1", 3)  # a wrong one, locked

        sealed, _ = service.submit(lesson, attempt.id, {"t1": right(QUESTIONS[0]), "t2": right(QUESTIONS[1])})

        assert sealed.answers == {"t1": 3, "t2": right(QUESTIONS[1])}
        assert sealed.awarded == MARKS["t2"]

    def test_an_answer_for_an_unknown_question_is_refused_and_nothing_is_sealed(self, make_lesson, queue):
        lesson, service, attempt = self.started(make_lesson, queue)

        with pytest.raises(InvalidAnswers, match="Unknown question ids: nope"):
            service.submit(lesson, attempt.id, {"nope": 1})

        assert TestSubmission.objects.get(pk=attempt.pk).status == "in_progress"

    def test_a_sealed_attempt_cannot_be_submitted_again(self, make_lesson, queue):
        lesson, service, attempt = self.started(make_lesson, queue)
        service.submit(lesson, attempt.id, all_right())

        with pytest.raises(AttemptSealed):
            service.submit(lesson, attempt.id, {"t1": 0})

        assert TestSubmission.objects.get(pk=attempt.pk).awarded == 20

    def test_an_attempt_that_is_still_preparing_cannot_be_submitted(self, make_lesson, queue):
        lesson = ready(make_lesson)
        graded_attempt(lesson)
        service = AttemptService(queue=queue)
        waiting = service.start(lesson).attempt

        with pytest.raises(WrongStage):
            service.submit(lesson, waiting.id)

    def test_the_gate_is_not_asked_when_submitting(self, make_lesson, queue):
        gate = CountingGate()
        lesson, service, attempt = self.started(make_lesson, queue, gate=gate)

        service.submit(lesson, attempt.id, all_right())

        assert gate.authorized == []

    def test_a_legacy_attempt_with_open_ended_questions_is_marked_as_far_as_it_can_be_and_queued(
        self, make_lesson, queue
    ):
        legacy = make_final_test()
        lesson = ready(make_lesson, final_test=legacy, plan=None)
        service = AttemptService(queue=queue)
        attempt = service.start(lesson).attempt
        ids = {q["type"]: q["id"] for q in legacy["questions"]}

        sealed, run = service.submit(lesson, attempt.id, {ids["mcq"]: 1, ids["short_answer"]: "Halve it."})

        assert sealed.status == "grading" and sealed.result["complete"] is False
        assert (sealed.awarded, sealed.available, sealed.band) == (None, None, "")
        assert (run.graph, run.trigger) == (GraphRun.Graph.GRADE_TEST, GraphRun.Trigger.GRADE)
        assert run.payload == {"input": {"submission_id": str(sealed.id)}} and queue.runs == [run]

    def test_a_legacy_first_attempt_keeps_its_own_total(self, make_lesson, queue):
        legacy = make_final_test()
        lesson = ready(make_lesson, final_test=legacy, plan=None)
        service = AttemptService(queue=queue)
        attempt = service.start(lesson).attempt

        sealed, _ = service.submit(lesson, attempt.id, {})

        assert sealed.available == sum(q["marks"] for q in legacy["questions"]) and sealed.available != 20


class TestOnlySealWritesAnAttemptsAnswers:
    def test_no_code_outside_the_attempt_service_updates_the_answers_or_the_questions_of_an_attempt(self):
        """The immutability rule of docs/architecture/data-model.md: `seal()` is the way out of in_progress, and the
        answer endpoint the way in. Anything else that updated these two fields would break it."""
        offenders = []
        backend = pathlib.Path(lessons.__file__).parent.parent
        allowed = {
            "lessons/attempts.py",  # saves an answer, locking the question
            "lessons/models.py",  # `TestSubmission.seal`, the one way out of in_progress
            "graph/nodes/bank.py",  # the retake graph fills a generating attempt once and starts it
        }
        for path in backend.rglob("*.py"):
            if {"migrations", ".venv", "node_modules"} & set(path.parts) or str(path.relative_to(backend)) in allowed:
                continue
            source = path.read_text()
            if "TestSubmission" not in source:  # cheap text test first: parsing every file of the backend took 13 s
                continue
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "update":
                    names = {kw.arg for kw in node.keywords}
                    if "TestSubmission" in ast.unparse(node.func) and names & {"answers", "questions"}:
                        offenders.append(f"{path.relative_to(backend)}:{node.lineno}")
        assert offenders == []


class TestHistory:
    def test_it_lists_every_attempt_oldest_first_with_the_trend_of_the_graded_ones(self, make_lesson):
        lesson = ready(make_lesson)
        graded_attempt(lesson, 1, awarded=10)
        graded_attempt(lesson, 2, awarded=16)
        TestSubmission.objects.create(lesson=lesson, attempt_no=3, status="generating")

        body = AttemptService().history(lesson)

        assert [a["attempt_no"] for a in body["attempts"]] == [1, 2, 3]
        assert [a["percent"] for a in body["attempts"]] == [50, 80, None]
        assert [p.percent for p in body["trend"].series] == [50, 80] and body["trend"].series[1].delta_previous == 30

    def test_the_latest_attempt_is_the_one_with_the_highest_number(self, make_lesson):
        lesson = ready(make_lesson)
        graded_attempt(lesson, 1)
        latest = graded_attempt(lesson, 2)

        assert AttemptService().current(lesson).pk == latest.pk

    def test_a_lesson_with_no_attempt_has_no_latest(self, make_lesson):
        with pytest.raises(SubmissionNotFound):
            AttemptService().current(ready(make_lesson))


def test_an_attempt_of_another_lesson_is_not_found_when_answering_through_this_one(make_lesson, queue):
    lesson = ready(make_lesson)
    other = ready(make_lesson, final_test={"title": "T", "questions": [make_question("mcq", 50)]})
    attempt = AttemptService(queue=queue).start(other).attempt

    with pytest.raises(SubmissionNotFound):
        AttemptService(queue=queue).save_answer(lesson, attempt.id, "t50", 1)
