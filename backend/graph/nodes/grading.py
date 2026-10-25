"""The `grade_test` graph: the open-ended answers of a submitted lesson test, graded by a model.

load_submission → (nothing open to grade → persist_grade) | grade_open (test.grade) → validate_grade → persist_grade.
Questions with one right answer and blank answers are marked in code (`ScoreCard`), so the model sees only answers
that deserve a judgement. There is no Retry: a run that cannot grade ends with its reason, the submission is marked
failed, and the learner submits again.
"""

from django.utils import timezone

from lessons.models import Lesson, TestSubmission

from ..context import FlowContext
from ..errors import RunFailed
from ..grading import AnswerGrader, ScoreCard
from ..prompts import GradeTestPrompt
from ..schemas import GradeReport
from ..validators import GradeReportValidator, Validator
from .base import LLMNode, Node, ValidateNode
from .routers import Router


class LoadSubmissionNode(Node):
    name = "load_submission"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        lesson = Lesson.objects.select_related("owner__profile").get(pk=state["lesson_id"])
        submission = TestSubmission.objects.get(pk=state["submission_id"], lesson=lesson)
        profile = lesson.owner.profile
        return {
            "topic": lesson.topic,
            "profile": {"preferred_language": profile.preferred_language},
            "snapshot": lesson.config_snapshot,
            "settings": lesson.settings_snapshot,
            "final_test": lesson.final_test,
            "test_answers": submission.answers,
            "grading_items": ScoreCard().open_items(lesson.final_test["questions"], submission.answers),
        }


class OpenItemsRouter(Router):
    """Ask the model only when some answer needs a judgement."""

    def __call__(self, state: dict) -> str:
        return "grade_open" if state["grading_items"] else "persist_grade"


class GradeOpenNode(LLMNode):
    name = "grade_open"
    node_key = "test.grade"
    prompt = GradeTestPrompt()
    schema = GradeReport
    feedback_key = "grading"

    def subject(self, state: dict) -> dict:
        return {"topic": state["topic"], "profile": state.get("profile"), "items": state["grading_items"]}

    def to_state(self, output: GradeReport, state: dict, ctx: FlowContext) -> dict:
        return {"grade_report": output.model_dump(mode="json"), "attempts": {"grading": 1}}


class ValidateGradeNode(ValidateNode):
    name = "validate_grade"
    node_key = "test.grade"
    feedback_key = "grading"
    retry_node = "grade_open"
    label = "The grading"

    def validator(self, state: dict, ctx: FlowContext) -> Validator:
        return GradeReportValidator()

    def subject(self, state: dict) -> dict:
        return state["grade_report"]

    def context(self, state: dict) -> dict:
        return {"questions": state["grading_items"]}


class PersistGradeNode(Node):
    """The finished `ScoreCard` goes onto the submission."""

    name = "persist_grade"

    def __init__(self, cards: ScoreCard | None = None, grader: AnswerGrader | None = None):
        self.cards = cards or ScoreCard()
        self.grader = grader or AnswerGrader()

    def run(self, state: dict, ctx: FlowContext) -> dict:
        questions, answers = state["final_test"]["questions"], state["test_answers"]
        graded = {g["question_id"]: g for g in (state.get("grade_report") or {}).get("grades", [])}
        card = self.cards.build(questions, answers, self.grader.grade_all(questions, answers), graded)
        TestSubmission.objects.filter(pk=state["submission_id"]).update(
            result=card, status=TestSubmission.Status.GRADED, error="", graded_at=timezone.now()
        )
        return {}


class FailGradeNode(Node):
    name = "fail_grade"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        raise RunFailed(state.get("error") or "The test could not be graded.")
