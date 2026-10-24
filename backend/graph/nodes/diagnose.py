"""Stage A: diagnose. Generate and validate the quizzes, pause for the learner, grade, route, assess."""

from langgraph.runtime import Runtime
from langgraph.types import interrupt

from lessons.models import Lesson, Quiz, QuizAttempt, Stage

from .. import grading, prompts, validators
from ..context import FlowContext, emit, llm, node_settings
from ..schemas import DiagnosticBundle, LearnerAssessment, QuizReview
from .common import learner_profile, outcome, route_check, set_stage, update_lesson


def load_context(state, runtime: Runtime[FlowContext]):
    lesson = Lesson.objects.select_related("owner__profile").get(pk=state["lesson_id"])
    return {
        "topic": lesson.topic,
        "user_context": lesson.user_context,
        "profile": learner_profile(lesson.owner.profile),
        "snapshot": lesson.config_snapshot,
        "settings": lesson.settings_snapshot,
    }


def generate_diagnostic(state, runtime: Runtime[FlowContext]):
    set_stage(state["lesson_id"], Stage.PREPARING_DIAGNOSTIC)
    feedback = (state.get("feedback") or {}).get("diagnostic")
    result = llm(runtime, state, "diagnostic.generate", prompts.diagnostic(state, feedback), schema=DiagnosticBundle)
    return {"bundle": result.output.model_dump(mode="json"), "attempts": {"diagnostic": 1}}


def validate_diagnostic(state, runtime: Runtime[FlowContext]):
    problems = validators.validate_diagnostic(state["bundle"], state["settings"], latex=runtime.context.sandbox.latex)
    if not problems and node_settings(state, "diagnostic.review")["enabled"]:
        review = llm(runtime, state, "diagnostic.review", prompts.diagnostic_review(state, state["bundle"]),
                     schema=QuizReview)  # fmt: skip
        problems = [f"Question {issue.question_id}: {issue.problem}" for issue in review.output.issues]
    return outcome(state, "diagnostic", "diagnostic.generate", problems, "generate_diagnostic", "The diagnostic quiz")


def after_validate_diagnostic(state) -> str:
    return route_check(state, "diagnostic", ok="publish_diagnostic", retry="generate_diagnostic")


def publish_diagnostic(state, runtime: Runtime[FlowContext]):
    quiz, _ = Quiz.objects.update_or_create(
        lesson_id=state["lesson_id"], kind=Quiz.Kind.DIAGNOSTIC, defaults={"questions": state["bundle"]["diagnostic"]}
    )
    set_stage(state["lesson_id"], Stage.AWAITING_DIAGNOSTIC)
    emit({"type": "awaiting_input", "kind": "diagnostic", "quiz_id": str(quiz.id)})
    return {"diagnostic_quiz_id": str(quiz.id)}


def await_diagnostic(state):
    # No side effects: LangGraph re-runs this node from the top when the thread resumes.
    attempt_id = interrupt({"kind": "diagnostic", "quiz_id": state["diagnostic_quiz_id"]})
    return {"diagnostic_attempt_id": attempt_id}


def _attempt(attempt_id: str) -> QuizAttempt:
    return QuizAttempt.objects.select_related("quiz").get(pk=attempt_id)


def grade_diagnostic(state, runtime: Runtime[FlowContext]):
    attempt = _attempt(state["diagnostic_attempt_id"])
    result = grading.grade_quiz(attempt.quiz.questions, attempt.answers)
    route = grading.route_for(result, state["settings"])
    fields = {"route": route}
    if route == "lesson":
        set_stage(state["lesson_id"], Stage.GENERATING_LESSON, prerequisites_to_cover=[], **fields)
    else:
        update_lesson(state["lesson_id"], **fields)
    return {"diagnostic_result": result, "route": route, "prerequisites_to_cover": []}


def route_level(state) -> str:
    return {"mastery": "publish_mastery_options", "prerequisite": "publish_prerequisite"}.get(
        state["route"], "assess_learner"
    )


def publish_prerequisite(state, runtime: Runtime[FlowContext]):
    bundle = state["bundle"]
    quiz, _ = Quiz.objects.update_or_create(
        lesson_id=state["lesson_id"],
        kind=Quiz.Kind.PREREQUISITE,
        defaults={"questions": bundle["prerequisite_questions"], "prerequisites": bundle["prerequisites"]},
    )
    set_stage(state["lesson_id"], Stage.AWAITING_PREREQUISITE)
    emit({"type": "awaiting_input", "kind": "prerequisite", "quiz_id": str(quiz.id)})
    return {"prerequisite_quiz_id": str(quiz.id)}


def await_prerequisite(state):
    attempt_id = interrupt({"kind": "prerequisite", "quiz_id": state["prerequisite_quiz_id"]})
    return {"prerequisite_attempt_id": attempt_id}


def grade_prerequisite(state, runtime: Runtime[FlowContext]):
    attempt = _attempt(state["prerequisite_attempt_id"])
    result = grading.grade_quiz(attempt.quiz.questions, attempt.answers)
    to_cover = grading.prerequisites_to_cover(attempt.quiz.prerequisites or [], attempt.quiz.questions, result)
    set_stage(state["lesson_id"], Stage.GENERATING_LESSON, prerequisites_to_cover=to_cover)
    return {"prerequisite_result": result, "prerequisites_to_cover": to_cover}


def assess_learner(state, runtime: Runtime[FlowContext]):
    set_stage(state["lesson_id"], Stage.GENERATING_LESSON)
    bundle = state["bundle"]
    messages = prompts.assess_learner(state, bundle["diagnostic"], bundle["prerequisite_questions"])
    result = llm(runtime, state, "learner.assess", messages, schema=LearnerAssessment)
    assessment = validators.assessment_guard(result.output.model_dump(mode="json"), state["prerequisites_to_cover"])
    update_lesson(state["lesson_id"], assessment=assessment, level=assessment["level"])
    return {"assessment": assessment}
