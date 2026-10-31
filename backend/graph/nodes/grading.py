"""The grading graph: the open-ended answers of a submitted attempt, graded by a model. It marks a legacy lesson attempt
(`grade_test`) and a quick quiz's (`grade_quiz`) alike, through an `AttemptStore`.

load_submission → (nothing open to grade → persist_grade) | grade_open (test.grade) → validate_grade → persist_grade.
Questions with one right answer and blank answers are marked in code (`ScoreCard`), so the model sees only answers
that deserve a judgement. There is no Retry: a run that cannot grade ends with its reason, the attempt is marked
failed, and the learner submits again.
"""

from ..attempt_stores import AttemptStore, LessonAttemptStore
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

    def __init__(self, store: AttemptStore | None = None):
        self.store = store or LessonAttemptStore()

    def run(self, state: dict, ctx: FlowContext) -> dict:
        attempt = self.store.load(state)
        return {
            "topic": attempt.topic,
            "profile": attempt.profile,
            "snapshot": attempt.snapshot,
            "settings": attempt.settings,
            "final_test": {"questions": attempt.questions},  # what this attempt was served, not the lesson's test
            "test_answers": attempt.answers,
            "grading_items": ScoreCard().open_items(attempt.questions, attempt.answers),
            **attempt.state,
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
    """The finished `ScoreCard` goes onto the attempt, with its band and, for a lesson attempt, the offer that follows
    (the store decides: `AttemptOutcome` is the rule a lesson attempt meets at submit)."""

    name = "persist_grade"

    def __init__(
        self,
        cards: ScoreCard | None = None,
        grader: AnswerGrader | None = None,
        store: AttemptStore | None = None,
    ):
        self.cards = cards or ScoreCard()
        self.grader = grader or AnswerGrader()
        self.store = store or LessonAttemptStore()

    def run(self, state: dict, ctx: FlowContext) -> dict:
        questions, answers = state["final_test"]["questions"], state["test_answers"]
        graded = {g["question_id"]: g for g in (state.get("grade_report") or {}).get("grades", [])}
        card = self.cards.build(questions, answers, self.grader.grade_all(questions, answers), graded)
        self.store.save(state, card)
        return {}


class FailGradeNode(Node):
    name = "fail_grade"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        raise RunFailed(state.get("error") or "The test could not be graded.")
