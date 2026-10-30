"""Unit under test: the `question_bank` graph (`graph.builders.QuestionBankGraphBuilder`): the questions of a retake.

Why: a retake that repeats a question measures memory, one that comes back with nine questions is not comparable to the
first attempt, and one that is stopped must not leave a half-made attempt. The nodes pass their own tests; the wiring
decides that all ten cells are filled with new questions, that only what failed is written again, and that the waiting
attempt only starts when its set is whole.

Use cases:
- a retake fills the ten cells of the lesson's blueprint with new questions in two batches, puts them on the record, and
  moves the waiting attempt to in_progress with the questions in blueprint order
- everything the lesson has asked (its test, earlier attempts, retired questions of an old test) is given to the model
  as questions not to repeat
- a lesson made before the blueprint gets the blueprint its old test implies, and keeps it
- an unserved question on the record fills its cell with no model call, and only the other cells are written
- a batch that fails its rules is written again alone; a question that repeats an earlier one is replaced in a second
  round; a test that cannot be filled ends the run with the reason and the attempt stays generating
- an attempt that is gone (the retake was stopped) fails the run and writes nothing
- the lesson itself stays ready
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from support.fixtures import budget_snapshot
from support.lesson_data import make_assessment, make_blueprint_test, make_final_test, make_plan
from support.question_data import ScriptedQuestions, written

from graph.builders import QuestionBankGraphBuilder
from graph.errors import RunFailed
from graph.questions import LessonTestBlueprint
from graph.schemas import QuestionBatch
from lessons.bank import QuestionBank
from lessons.models import Lesson, Question, Stage, TestSubmission

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def retake(lesson, lesson_state):
    """A ready lesson with its test on the record, a graded first attempt, and attempt 2 waiting for its questions."""
    test = make_blueprint_test()
    stored = {"title": test["title"], "questions": QuestionBank().add(lesson.id, None, test["questions"])}
    Lesson.objects.filter(pk=lesson.pk).update(
        stage=Stage.READY, assessment=make_assessment(), plan=make_plan(), final_test=stored,
        test_blueprint=LessonTestBlueprint.for_topic(True).to_json(), config_snapshot=budget_snapshot(),
        settings_snapshot=lesson_state["settings"],
    )  # fmt: skip
    TestSubmission.objects.create(
        lesson=lesson, attempt_no=1, status="graded", questions=stored["questions"], answers={}
    )
    return TestSubmission.objects.create(lesson=lesson, attempt_no=2, status="generating", questions=[])


def run(attempt, ctx):
    graph = QuestionBankGraphBuilder().build(InMemorySaver())
    start = {"lesson_id": str(attempt.lesson_id), "attempt_id": str(attempt.id)}
    nodes = []
    for chunk in graph.stream(start, {"configurable": {"thread_id": "t"}}, context=ctx, stream_mode="updates"):
        nodes += list(chunk)
    return nodes


@pytest.fixture
def questions(gateway):
    scripted = ScriptedQuestions()
    scripted.written = 100  # new texts, never the first test's
    gateway.respond("test.generate", scripted)
    return scripted


def test_a_retake_fills_the_ten_cells_and_starts_the_waiting_attempt(retake, ctx, gateway, questions, lesson):
    nodes = run(retake, ctx)

    assert nodes == [
        "load_bank", "plan_batches", "generate_questions", "generate_questions", "questions_join", "persist_attempt",
    ]  # fmt: skip
    attempt = TestSubmission.objects.get(pk=retake.pk)
    assert attempt.status == "in_progress" and attempt.attempt_no == 2 and attempt.submitted_at is None
    assert [q["id"] for q in attempt.questions] == [f"t{n}" for n in range(1, 11)]
    assert [(q["type"], q["difficulty"]) for q in attempt.questions] == [
        (c.type, c.difficulty) for c in LessonTestBlueprint.for_topic(True).cells
    ]
    assert sum(q["marks"] for q in attempt.questions) == 20
    assert Question.objects.filter(lesson=lesson).count() == 20  # the first test's ten and these ten
    assert {q["question_id"] for q in attempt.questions} <= {str(r.id) for r in Question.objects.filter(lesson=lesson)}
    assert Lesson.objects.get(pk=lesson.pk).stage == Stage.READY
    assert len(gateway.called("test.generate")) == 2


def test_every_question_the_lesson_has_asked_is_given_to_the_model_to_avoid(retake, ctx, gateway, questions, lesson):
    run(retake, ctx)

    prompt = gateway.called("test.generate")[0].messages[1].content
    for question in make_blueprint_test()["questions"]:
        assert question["question"] in prompt


def test_a_lesson_made_before_the_blueprint_gets_the_one_its_old_test_implies_and_keeps_it(
    lesson, lesson_state, ctx, gateway, questions
):
    Lesson.objects.filter(pk=lesson.pk).update(
        stage=Stage.READY, assessment=make_assessment(), plan=make_plan(), final_test=make_final_test(),
        config_snapshot=budget_snapshot(), settings_snapshot=lesson_state["settings"], test_blueprint=None,
    )  # fmt: skip
    TestSubmission.objects.create(
        lesson=lesson, attempt_no=1, status="graded", questions=make_final_test()["questions"]
    )
    waiting = TestSubmission.objects.create(lesson=lesson, attempt_no=2, status="generating", questions=[])

    run(waiting, ctx)

    stored = Lesson.objects.get(pk=lesson.pk).test_blueprint
    assert stored == LessonTestBlueprint.for_topic(True).to_json()  # the old test had numerical questions
    assert TestSubmission.objects.get(pk=waiting.pk).status == "in_progress"


def test_an_unserved_question_on_the_record_fills_its_cell_with_no_model_call(retake, ctx, gateway, questions, lesson):
    spare = {**make_blueprint_test()["questions"][0], "question": "A spare mcq about the midpoint?", "id": "t77"}
    (stored,) = QuestionBank().add(lesson.id, None, [spare])

    nodes = run(retake, ctx)

    attempt = TestSubmission.objects.get(pk=retake.pk)
    assert attempt.questions[0]["question_id"] == stored["question_id"] and attempt.questions[0]["id"] == "t1"
    assert attempt.questions[0]["question"] == "A spare mcq about the midpoint?"
    assert nodes.count("generate_questions") == 2
    first_prompt = gateway.called("test.generate")[0].messages[0].content
    assert (
        "exactly 5 questions" in first_prompt
        and "exactly 4 questions" in gateway.called("test.generate")[1].messages[0].content
    )


def test_a_batch_that_fails_its_rules_is_written_again_alone(retake, ctx, gateway, questions):
    questions.spoilers.append((lambda cells: True, lambda qs, so_far: qs[0].update(difficulty="expert")))

    nodes = run(retake, ctx)

    assert nodes.count("generate_questions") == 3 and nodes[-1] == "persist_attempt"
    assert TestSubmission.objects.get(pk=retake.pk).status == "in_progress"


def test_a_question_that_repeats_an_earlier_one_is_replaced_in_a_second_round(retake, ctx, gateway, questions):
    second_batch = lambda cells: cells[0] == ("numerical", "standard")  # noqa: E731
    questions.spoilers.append((second_batch, lambda qs, so_far: qs[0].update(question=so_far[0]["question"])))

    nodes = run(retake, ctx)

    assert nodes.count("plan_batches") == 2 and nodes.count("generate_questions") == 3
    texts = [q["question"] for q in TestSubmission.objects.get(pk=retake.pk).questions]
    assert len(set(texts)) == 10


def test_a_test_that_cannot_be_filled_ends_the_run_with_the_reason_and_the_attempt_stays_waiting(retake, ctx, gateway):
    def only_easy_mcq(messages):
        count = len(ScriptedQuestions.LINE.findall(messages[0].content))
        return QuestionBatch(
            questions=[written("mcq", 200 + n + len(gateway.calls) * 10, "easy") for n in range(count)]
        )

    gateway.respond("test.generate", only_easy_mcq)

    with pytest.raises(RunFailed, match="The test could not be filled"):
        run(retake, ctx)

    assert TestSubmission.objects.get(pk=retake.pk).status == "generating"
    assert Question.objects.filter(lesson=retake.lesson).count() == 10  # nothing new was recorded


def test_an_attempt_that_is_gone_before_the_run_starts_fails_the_run(retake, ctx, gateway, questions):
    TestSubmission.objects.filter(pk=retake.pk).delete()

    with pytest.raises(RunFailed, match="That retake was cancelled"):
        run(retake, ctx)

    assert gateway.called("test.generate") == []


def test_an_attempt_that_is_stopped_while_its_questions_are_written_writes_nothing(retake, ctx, gateway, questions):
    inner = questions

    def stopped_meanwhile(messages):
        TestSubmission.objects.filter(pk=retake.pk).delete()  # the learner pressed Stop; the effect removed the row
        return inner(messages)

    gateway.respond("test.generate", stopped_meanwhile)

    with pytest.raises(RunFailed, match="That retake was cancelled"):
        run(retake, ctx)

    assert (
        Question.objects.filter(lesson=retake.lesson).count() == 10
        and not TestSubmission.objects.filter(pk=retake.pk).exists()
    )
