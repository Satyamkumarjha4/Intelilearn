"""The `quick_quiz` graph (plan §9.4): a quiz's first questions, and every retake's.

    load_quiz → resolve_source → (a level already known | level_from_rating | level_from_scores | the calibration walk)
              → plan_quiz → plan_batches → Send per batch → generate_questions → questions_join → persist_attempt

The calibration walk is `generate_pool → validate_pool → publish_calibration → await_calibration → level_from_walk`. The
walk itself is driven by the API one answer at a time and calls no model (`AdaptiveLadder`); the graph pauses at
`await_calibration` and resumes once, when the walk is over. The question nodes are the ones the lesson test uses
(`graph/nodes/questions.py`), so a quiz and a test can never drift apart.
"""

from django.db import transaction
from django.utils import timezone

from quizzes.models import QuickQuiz, QuickQuizAttempt
from quizzes.stages import QuizStage

from ..assessment import AssessmentRequest, AssessmentSources
from ..concept_index import ConceptIndex
from ..context import FlowContext
from ..errors import RunFailed
from ..levels import Level, LevelScheme
from ..profile import LearnerProfile
from ..prompts import DiagnosticPrompt
from ..questions import Blueprints, QuestionTypes, QuizBlueprint, SourcePart, TopicTraits
from ..quiz_config import QuizConfig
from ..quiz_sources import ConceptSummaries, ConceptSummary, LevelMean
from ..schemas import DiagnosticBundle
from ..validators import DiagnosticValidator, Validator
from .base import AwaitNode, LLMNode, Node, PublishNode, ValidateNode
from .routers import Router

#: the calibration pool has two questions for each band, whatever the diagnostic's setting says
POOL_PER_BAND = 2


class QuizNode(Node):
    """A node of the quiz graph: it reads and writes the quiz, never a lesson."""

    @staticmethod
    def quiz(state: dict) -> QuickQuiz:
        return QuickQuiz.objects.get(pk=state["quiz_id"])


class LoadQuizNode(QuizNode):
    """Everything the graph needs from the database, once: the quiz, the attempt that waits for its questions, its
    settings,
    the level if it is known already (a retake), and every question the quiz has asked, so none comes back."""

    name = "load_quiz"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        quiz = QuickQuiz.objects.select_related("owner__profile").get(pk=state["quiz_id"])
        waiting = QuickQuizAttempt.objects.filter(
            pk=state["attempt_id"], quiz=quiz, status=QuickQuizAttempt.Status.GENERATING
        ).exists()
        if not waiting:
            raise RunFailed("That quiz was cancelled.")
        config = QuizConfig.from_dict(quiz.config)
        asked = (
            q["question"] for snapshot in quiz.attempts.values_list("questions", flat=True) for q in snapshot or []
        )
        return {
            "topic": quiz.topic,
            "user_context": "",
            "profile": LearnerProfile.of(quiz.owner.profile).as_dict(),
            "snapshot": quiz.config_snapshot,
            "settings": quiz.settings_snapshot,
            "level_scheme": LevelScheme.CURRENT,
            "config": config.as_dict(),
            "traits": quiz.config.get("traits"),
            "source_type": quiz.source_type,
            "assessment": quiz.assessment,
            "exclusions": list(dict.fromkeys(asked)),
            "batch_capped": config.capped,
            "question_round": 0,
            "accepted": {},
        }


class ResolveSourceNode(QuizNode):
    """What a quiz from lessons is about: each lesson's share, its level and a summary of its plan, made in code within
    the token budget. Never the lesson's pages. A topic quiz has no sources."""

    name = "resolve_source"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        budget = (state.get("settings") or {}).get("quiz_source_token_budget", 1500)
        sources = []
        for row in self.quiz(state).sources.select_related("lesson"):
            if row.lesson is None:
                raise RunFailed("A lesson this quiz was made from has been deleted, so the quiz cannot be taken again.")
            summary = ConceptSummaries().of(
                row.lesson.plan or {}, budget, ConceptIndex.from_json(row.lesson.concept_index)
            )
            sources.append({
                "key": str(row.lesson_ref), "title": row.title, "level": row.level, "share": row.share,
                "summary": summary.as_dict(),
            })  # fmt: skip
        return {"sources": sources}


class LevelModeRouter(Router):
    """After the sources: a quiz whose level is known (a retake) goes on; otherwise the level mode decides."""

    DESTINATIONS = {
        "self_rating": "level_from_rating",
        "existing_score": "level_from_scores",
        "calibration": "generate_pool",
    }

    def __call__(self, state: dict) -> str:
        if state.get("assessment"):
            return "plan_quiz"
        return self.DESTINATIONS[state["config"]["level_mode"]]


class LevelFromRatingNode(QuizNode):
    name = "level_from_rating"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        request = AssessmentRequest(self_rating_halves=state["config"]["self_rating_halves"])
        assessment = AssessmentSources.for_key("self_rating").assess(request)
        self.quiz(state).record(assessment=assessment)
        return {"assessment": assessment}


class LevelFromScoresNode(QuizNode):
    """The learner's test scores already set each lesson's level (when the quiz was made): the quiz reports the"
    " middle one."""

    name = "level_from_scores"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        level = LevelMean.of([source["level"] for source in state["sources"]])
        request = AssessmentRequest(base_level=level.value, band="normal")
        assessment = AssessmentSources.for_key("test_score").assess(request)
        self.quiz(state).record(assessment=assessment)
        return {"assessment": assessment}


class GeneratePoolNode(LLMNode):
    """The calibration walk's questions: the diagnostic's own, two for each band and no prerequisite half."""

    name = "generate_pool"
    node_key = "diagnostic.generate"
    prompt = DiagnosticPrompt()
    schema = DiagnosticBundle
    feedback_key = "pool"

    def subject(self, state: dict) -> dict:
        settings = {**state["settings"], "diagnostic_questions_per_band": POOL_PER_BAND}
        return state | {"settings": settings, "include_prerequisites": False}

    def to_state(self, output: DiagnosticBundle, state: dict, ctx: FlowContext) -> dict:
        return {"bundle": output.model_dump(mode="json"), "attempts": {"pool": 1}}


class ValidatePoolNode(ValidateNode):
    name = "validate_pool"
    node_key = "diagnostic.generate"
    feedback_key = "pool"
    retry_node = "generate_pool"
    label = "The calibration questions"

    def validator(self, state: dict, ctx: FlowContext) -> Validator:
        return DiagnosticValidator(ctx.sandbox)

    def subject(self, state: dict) -> dict:
        return state["bundle"]

    def context(self, state: dict) -> dict:
        return {"settings": {**state["settings"], "diagnostic_questions_per_band": POOL_PER_BAND},
                "include_prerequisites": False}  # fmt: skip


class PublishCalibrationNode(PublishNode, QuizNode):
    """The pool is kept on the quiz (server-side only: it holds the answers) and the quiz waits for the walk."""

    name = "publish_calibration"

    def publish(self, state: dict, ctx: FlowContext) -> dict:
        quiz = self.quiz(state)
        quiz.advance_to(QuizStage.AWAITING_CALIBRATION, calibration={"pool": state["bundle"]["diagnostic"], "walk": []})
        return {}


class AwaitCalibrationNode(AwaitNode):
    name = "await_calibration"
    kind = "calibration"
    result_key = "calibration_done"

    def payload(self, state: dict) -> dict:
        return {"quiz_id": state["quiz_id"]}


class LevelFromWalkNode(QuizNode):
    """The walk is over (the API stored every answer): the ladder's table gives the level."""

    name = "level_from_walk"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        quiz = self.quiz(state)
        answers = [step["correct"] for step in (quiz.calibration or {}).get("walk") or []]
        assessment = AssessmentSources.for_key("calibration").assess(AssessmentRequest(walk=answers))
        quiz.advance_to(QuizStage.PREPARING, assessment=assessment)
        return {"assessment": assessment}


class PlanQuizNode(QuizNode):
    """The cells of the quiz, decided in code from the settings, the sources and the level: how many questions of which
    kind and difficulty about which lesson, and what the question writer is told."""

    name = "plan_quiz"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        config = QuizConfig.from_dict(state["config"])
        level = LevelScheme.level_of(state["assessment"])
        sources = state.get("sources") or []
        if sources:
            # The learner's own mode (a rating, a calibration) sets one level for every lesson; their scores keep each
            # lesson at the level its score gave.
            parts = [SourcePart(s["key"], self.level_of(s, config, level), s["share"]) for s in sources]
            blueprint = QuizBlueprint.for_lessons(parts, config.types)
        else:
            parts = []
            blueprint = QuizBlueprint.for_topic(config.num_questions, config.types, level)
        traits = TopicTraits.from_dict(state.get("traits"))
        about = {
            part.key: {
                "title": source["title"],
                "level": part.level.value,
                "summary": ConceptSummary.from_dict(source["summary"]).text(),
                "concepts": [c["concept"] for c in source["summary"]["concepts"]],
            }  # fmt: skip
            for part, source in zip(parts, sources, strict=True)
        }
        quiz = {"level": level.value, "code_format": QuestionTypes.code_format(traits, config.types), "sources": about}
        return {"blueprint": blueprint.to_json(), "quiz": quiz, "accepted": {}, "question_round": 0}

    @staticmethod
    def level_of(source: dict, config: QuizConfig, quiz_level: Level) -> Level:
        return Level.parse(source["level"]) if config.level_mode == "existing_score" else quiz_level


class PersistQuizAttemptNode(QuizNode):
    """The set becomes the attempt's questions and the attempt starts: `generating` → `in_progress`. The quiz that was
    being made is now ready (a retake finds it ready already). If the attempt is gone (the quiz was stopped or deleted),
    nothing is written."""

    name = "persist_attempt"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        blueprint = Blueprints.from_json(state["blueprint"])
        accepted = state.get("accepted") or {}
        questions = [
            {**accepted[str(cell.index)], "source": cell.source} if cell.source else accepted[str(cell.index)]
            for cell in blueprint.cells
            if str(cell.index) in accepted
        ]
        if not questions:
            raise RunFailed("No question could be written for this quiz.")
        with transaction.atomic():
            started = QuickQuizAttempt.objects.filter(
                pk=state["attempt_id"], status=QuickQuizAttempt.Status.GENERATING
            ).update(questions=questions, status=QuickQuizAttempt.Status.IN_PROGRESS, started_at=timezone.now())
            if not started:
                raise RunFailed("That quiz was cancelled.")
            quiz = self.quiz(state)
            if quiz.stage == QuizStage.PREPARING:
                quiz.advance_to(QuizStage.READY)
        return {}
