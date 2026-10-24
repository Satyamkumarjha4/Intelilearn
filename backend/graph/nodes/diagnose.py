"""Stage A: diagnose. Generate and validate the quizzes, pause for the learner, grade, route, assess.

load_context → generate_diagnostic → validate_diagnostic → publish_diagnostic → await_diagnostic →
grade_diagnostic → (prerequisite: publish → await → grade) → assess_learner
"""

from typing import Any

from lessons.models import Lesson, Quiz, QuizAttempt, Stage

from ..context import FlowContext, NodeBudget
from ..grading import QuizResult, RoutingPolicy
from ..profile import LearnerProfile
from ..prompts import AssessLearnerPrompt, DiagnosticPrompt, DiagnosticReviewPrompt
from ..schemas import DiagnosticBundle, LearnerAssessment, QuizReview
from ..validators import (
    AssessmentGuard,
    CompositeValidator,
    DiagnosticReviewValidator,
    DiagnosticValidator,
    Validator,
)
from .base import AwaitNode, LLMNode, Node, PublishNode, ValidateNode


class LoadContextNode(Node):
    """Read what the graph needs from the database once, so later nodes work from the state."""

    name = "load_context"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        lesson = Lesson.objects.select_related("owner__profile").get(pk=state["lesson_id"])
        return {
            "topic": lesson.topic,
            "user_context": lesson.user_context,
            "profile": LearnerProfile.of(lesson.owner.profile).as_dict(),
            "snapshot": lesson.config_snapshot,
            "settings": lesson.settings_snapshot,
        }


class GenerateDiagnosticNode(LLMNode):
    name = "generate_diagnostic"
    node_key = "diagnostic.generate"
    prompt = DiagnosticPrompt()
    schema = DiagnosticBundle
    feedback_key = "diagnostic"

    def before(self, state: dict) -> None:
        self.lesson(state).advance_to(Stage.PREPARING_DIAGNOSTIC)

    def to_state(self, output: DiagnosticBundle, state: dict) -> dict:
        return {"bundle": output.model_dump(mode="json"), "attempts": {"diagnostic": 1}}


class ValidateDiagnosticNode(ValidateNode):
    name = "validate_diagnostic"
    node_key = "diagnostic.generate"
    feedback_key = "diagnostic"
    retry_node = "generate_diagnostic"
    label = "The diagnostic quiz"

    def validator(self, state: dict, ctx: FlowContext) -> Validator:
        # Deterministic rules first; the optional LLM reviewer only runs once those pass.
        return CompositeValidator(
            [
                DiagnosticValidator(ctx.sandbox),
                DiagnosticReviewValidator(lambda bundle: self.review(state, ctx, bundle)),
            ]
        )

    @staticmethod
    def review(state: dict, ctx: FlowContext, bundle: dict) -> list[tuple[str, str]]:
        if not NodeBudget.of(state, "diagnostic.review").enabled:
            return []
        messages = DiagnosticReviewPrompt().messages(state | {"bundle": bundle})
        report: QuizReview = ctx.invoke(state, "diagnostic.review", messages, schema=QuizReview).output
        return [(issue.question_id, issue.problem) for issue in report.issues]

    def subject(self, state: dict) -> dict:
        return state["bundle"]

    def context(self, state: dict) -> dict:
        return {"settings": state["settings"]}


class PublishDiagnosticNode(PublishNode):
    name = "publish_diagnostic"

    def publish(self, state: dict, ctx: FlowContext) -> dict:
        quiz, _ = Quiz.objects.update_or_create(
            lesson_id=state["lesson_id"],
            kind=Quiz.Kind.DIAGNOSTIC,
            defaults={"questions": state["bundle"]["diagnostic"]},
        )
        self.lesson(state).advance_to(Stage.AWAITING_DIAGNOSTIC)
        return {"diagnostic_quiz_id": str(quiz.id)}


class AwaitDiagnosticNode(AwaitNode):
    name = "await_diagnostic"
    kind = "diagnostic"
    result_key = "diagnostic_attempt_id"

    def payload(self, state: dict) -> dict:
        return {"quiz_id": state["diagnostic_quiz_id"]}


class GradeDiagnosticNode(Node):
    """Routing is deterministic. The API stored the graded result when the learner submitted; the graph reads it."""

    name = "grade_diagnostic"

    def __init__(self, policy: RoutingPolicy | None = None):
        self.policy = policy or RoutingPolicy()

    def run(self, state: dict, ctx: FlowContext) -> dict:
        attempt = QuizAttempt.objects.get(pk=state["diagnostic_attempt_id"])
        result = QuizResult.from_dict(attempt.result)
        route = self.policy.route_for(result, state["settings"])
        lesson = self.lesson(state)
        if route == "lesson":
            lesson.advance_to(Stage.GENERATING_LESSON, route=route, prerequisites_to_cover=[])
        else:
            lesson.record(route=route)
        return {"diagnostic_result": result.as_dict(), "route": route, "prerequisites_to_cover": []}


class PublishPrerequisiteNode(PublishNode):
    name = "publish_prerequisite"

    def publish(self, state: dict, ctx: FlowContext) -> dict:
        bundle = state["bundle"]
        quiz, _ = Quiz.objects.update_or_create(
            lesson_id=state["lesson_id"],
            kind=Quiz.Kind.PREREQUISITE,
            defaults={"questions": bundle["prerequisite_questions"], "prerequisites": bundle["prerequisites"]},
        )
        self.lesson(state).advance_to(Stage.AWAITING_PREREQUISITE)
        return {"prerequisite_quiz_id": str(quiz.id)}


class AwaitPrerequisiteNode(AwaitNode):
    name = "await_prerequisite"
    kind = "prerequisite"
    result_key = "prerequisite_attempt_id"

    def payload(self, state: dict) -> dict:
        return {"quiz_id": state["prerequisite_quiz_id"]}


class GradePrerequisiteNode(Node):
    name = "grade_prerequisite"

    def __init__(self, policy: RoutingPolicy | None = None):
        self.policy = policy or RoutingPolicy()

    def run(self, state: dict, ctx: FlowContext) -> dict:
        attempt = QuizAttempt.objects.select_related("quiz").get(pk=state["prerequisite_attempt_id"])
        result = QuizResult.from_dict(attempt.result)
        to_cover = self.policy.prerequisites_to_cover(attempt.quiz.prerequisites or [], attempt.quiz.questions, result)
        self.lesson(state).advance_to(Stage.GENERATING_LESSON, prerequisites_to_cover=to_cover)
        return {"prerequisite_result": result.as_dict(), "prerequisites_to_cover": to_cover}


class AssessLearnerNode(LLMNode):
    name = "assess_learner"
    node_key = "learner.assess"
    prompt = AssessLearnerPrompt()
    schema = LearnerAssessment

    def __init__(self, guard: AssessmentGuard | None = None):
        self.guard = guard or AssessmentGuard()

    def before(self, state: dict) -> None:
        self.lesson(state).advance_to(Stage.GENERATING_LESSON)

    def subject(self, state: dict) -> dict:
        bundle = state["bundle"]
        return state | {
            "diagnostic_questions": bundle["diagnostic"],
            "prerequisite_questions": bundle["prerequisite_questions"],
        }

    def to_state(self, output: Any, state: dict) -> dict:
        assessment = self.guard.apply(output.model_dump(mode="json"), state["prerequisites_to_cover"])
        self.lesson(state).record(assessment=assessment, level=assessment["level"])
        return {"assessment": assessment}
