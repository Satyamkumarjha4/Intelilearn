"""Unit under test: the quality of what the real models write for the question features of phases 9.1 to 9.7, measured
the way a person would judge it (plan §15.4).

Why: every other test fakes the models, so none can say whether a real model writes a multiple-select question with
two right answers, an expression that computes, a rubric that adds up, a lesson question that names the lesson's own
concept, a calibration pool with two questions per band, a retake that does not repeat itself, or a revision sheet that
covers the lesson. The product's validators already hold every question to most of these, so a failure here is a
question that was kept despite its problems, or a rule the validators do not state. They are slow, cost money, and are
never part of `make check`: run by hand with `pytest -m live` and the keys in `.env`.

Use cases:
- the real topic.traits model judges calculation and programming topics the way a person would
- lesson.plan sets quantitative for a calculation topic and not for a history topic
- the calibration pool has two valid multiple-choice questions in each of the five bands
- a quiz of every kind the topic offers: multiple-select questions have two or more right options, numerical expressions
  evaluate to their stored answer, short and long answers have criteria that add up to their marks
- a retake of that quiz does not ask again, in other words, what the first try asked
- a real lesson, and what comes from it: its test and a quiz made from it name only the lesson's own concepts, its
  index places them, and its revision sheet covers the concepts the product's rule demands
"""

import pytest
from live.golden import (
    GOLDEN_TOPICS,
    ConceptChecks,
    DedupeChecks,
    PlanChecks,
    PoolChecks,
    QuestionChecks,
    SheetChecks,
    TraitChecks,
)

from graph.concept_index import ConceptIndex
from graph.prompts import PlanLessonPrompt
from graph.questions import QuestionTypes
from graph.schemas import LessonPlan
from lessons.bank import QuestionBank
from lessons.models import Lesson, StudyMaterial
from lessons.services import MaterialService
from lessons.tasks import InlineTaskQueue
from llm_registry.gateway import Gateway
from llm_registry.resolver import RegistryResolver
from quizzes.attempts import QuizAttemptService
from quizzes.models import QuickQuiz
from quizzes.services import QuickQuizService
from quizzes.traits import GatewayTopicTraits, TopicTraitsService

pytestmark = [pytest.mark.live, pytest.mark.django_db(transaction=True)]


class Findings:
    """Collects what each check found, so one failing check does not hide the others, and prints the lot."""

    def __init__(self):
        self.rows: list[tuple[str, list[str]]] = []

    def check(self, name: str, problems: list[str]) -> None:
        self.rows.append((name, problems))

    def report(self) -> str:
        return "\n".join(
            f"{'PASS' if not p else 'FAIL'}  {n}" + "".join(f"\n        - {x}" for x in p) for n, p in self.rows
        )

    def assert_clean(self) -> None:
        print("\n" + self.report())
        failed = [name for name, problems in self.rows if problems]
        assert not failed, f"{len(failed)} of {len(self.rows)} checks failed:\n{self.report()}"


def questions_of(quiz: QuickQuiz, number: int = 1) -> list[dict]:
    return list(quiz.attempts.get(attempt_no=number).questions)


def test_the_topic_judge_agrees_with_a_person(real_registry):
    judged = {}
    for topic, _, _ in TraitChecks.EXPECTED:
        try:
            judged[topic] = GatewayTopicTraits().judge(topic)
        except Exception as exc:  # the model could not answer: reported, not hidden
            print(f"topic.traits failed for {topic!r}: {exc}")
            judged[topic] = None

    assert TraitChecks().problems(judged) == []


def test_lesson_plan_sets_the_quantitative_flag_sensibly(real_registry):
    from support.lesson_data import make_state

    flags = {}
    for topic, _ in PlanChecks.EXPECTED:
        messages = PlanLessonPrompt().messages(make_state() | {"topic": topic, "prerequisites_to_cover": []})
        result = Gateway().invoke("lesson.plan", messages, snapshot=RegistryResolver().snapshot(), schema=LessonPlan)
        flags[topic] = result.output.quantitative

    assert PlanChecks().problems(flags) == []


def test_the_calibration_pool_has_two_valid_questions_in_each_band(real_registry, learner):
    service = QuickQuizService(queue=InlineTaskQueue())

    made = service.create(
        learner, source={"type": "topic", "topic": "Photosynthesis"}, num_questions=5, types=["mcq"],
        level={"mode": "calibration"},
    )  # fmt: skip

    quiz = QuickQuiz.objects.get(pk=made.quiz.pk)
    assert quiz.stage == "awaiting_calibration", f"{quiz.stage}: {quiz.error}"
    assert PoolChecks().problems(quiz.calibration["pool"]) == []


def test_a_quiz_of_every_kind_is_well_formed_and_a_retake_does_not_repeat_it(real_registry, learner):
    topic = "Quadratic equations"
    traits = TopicTraitsService().of(topic).traits
    kinds = list(QuestionTypes.for_topic(traits, 10))
    service = QuickQuizService(queue=InlineTaskQueue())

    made = service.create(
        learner, source={"type": "topic", "topic": topic}, num_questions=10, types=kinds,
        level={"mode": "self_rating", "rating": 3},
    )  # fmt: skip
    quiz = QuickQuiz.objects.get(pk=made.quiz.pk)
    assert quiz.stage == "ready", f"{quiz.stage}: {quiz.error}"
    first = questions_of(quiz)
    # a retake needs the first try handed in: while one is open, it is the one a retake would return
    QuizAttemptService(queue=InlineTaskQueue()).submit(quiz, quiz.attempts.get(attempt_no=1).pk)
    service.retake(quiz)
    second = questions_of(QuickQuiz.objects.get(pk=quiz.pk), 2)

    findings = Findings()
    findings.check(
        "every kind that was asked for is there",
        [f"no {k} question" for k in kinds if k not in {q["type"] for q in first}],
    )
    findings.check("question quality (first try)", QuestionChecks().problems(first))
    findings.check("question quality (retake)", QuestionChecks().problems(second))
    findings.check("a retake does not repeat the first try", DedupeChecks().problems(first, second))
    findings.assert_clean()


def test_a_real_lesson_and_what_comes_from_it(rated_lesson):
    lesson = rated_lesson(GOLDEN_TOPICS[0].topic)
    assert lesson.stage == "ready", f"{lesson.stage}: {lesson.error}"
    index = ConceptIndex.from_json(lesson.concept_index)
    allowed = index.names()
    findings = Findings()

    findings.check(
        "the lesson has a concept index with every concept placed on a page",
        (
            []
            if index.entries and not index.unplaced
            else [f"{index.unplaced} of {len(index.entries)} concepts have no page"]
        ),
    )
    findings.check(
        "the lesson's test names only the lesson's concepts", ConceptChecks.problems(first_set(lesson), allowed)
    )
    findings.check("the lesson's test is well formed", QuestionChecks().problems(first_set(lesson)))

    quizzes = QuickQuizService(queue=InlineTaskQueue())
    made = quizzes.create(
        lesson.owner, source={"type": "lessons", "lesson_ids": [lesson.pk]}, num_questions=5, types=["mcq", "msq"],
        level={"mode": "self_rating", "rating": 3},
    )  # fmt: skip
    quiz = QuickQuiz.objects.get(pk=made.quiz.pk)
    asked = questions_of(quiz) if quiz.stage == "ready" else []
    findings.check("a quiz from the lesson was written", [] if asked else [f"{quiz.stage}: {quiz.error}"])
    findings.check("the quiz names only the lesson's concepts", ConceptChecks.problems(asked, allowed))
    findings.check("the quiz is well formed", QuestionChecks().problems(asked))

    materials = MaterialService(queue=InlineTaskQueue())
    materials.request_extra(lesson, "revision_sheet")
    sheet = StudyMaterial.objects.filter(lesson=lesson, kind="revision_sheet").first()
    coverage = SheetChecks()
    findings.check("the revision sheet was written", [] if sheet else ["no revision sheet came out"])
    if sheet:
        missing = coverage.missing(sheet.content, allowed)
        print(f"revision sheet covers {len(allowed) - len(missing)} of {len(allowed)} concepts; missing: {missing}")
        findings.check(
            "the revision sheet covers the lesson by the product's rule", coverage.problems(sheet.content, allowed)
        )
    findings.assert_clean()


def first_set(lesson: Lesson) -> list[dict]:
    """The questions the lesson was built with."""
    return QuestionBank().first_set(lesson)
