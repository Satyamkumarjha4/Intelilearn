"""The `question_bank` graph: a retake's questions.

    load_bank → plan_batches → Send per batch → generate_questions → questions_join → persist_attempt

It fills all ten cells of the lesson's blueprint with new questions, none of them a repeat of anything the lesson has
asked, and moves the attempt that was waiting (`generating`) to `in_progress`. The lesson itself stays `ready`. It is
the same pipeline as the author stage's (`graph/nodes/questions.py`); only the way in and the way out differ.
"""

import uuid

from django.db import transaction
from django.utils import timezone

from lessons.bank import QuestionBank
from lessons.models import Lesson, TestSubmission

from ..context import FlowContext
from ..errors import RunFailed
from ..profile import LearnerProfile
from ..questions import BlueprintSampler, LessonTestBlueprint
from .base import Node
from .questions import QuestionRound, QuestionSends
from .routers import Router


class LoadBankNode(Node):
    """Everything the retake needs from the database, once: the lesson, the attempt that waits for its questions, the
    blueprint (derived from the old test for a lesson made before it, and kept), what has been asked, and any
    question written but never served, which fills its cell without a model call."""

    name = "load_bank"

    def __init__(self, bank: QuestionBank | None = None, sampler: BlueprintSampler | None = None):
        self.bank = bank or QuestionBank()
        self.sampler = sampler or BlueprintSampler()

    def run(self, state: dict, ctx: FlowContext) -> dict:
        lesson = Lesson.objects.select_related("owner__profile").get(pk=state["lesson_id"])
        attempt = TestSubmission.objects.filter(
            pk=state["attempt_id"], lesson=lesson, status=TestSubmission.Status.GENERATING
        ).first()
        if attempt is None:
            raise RunFailed("That retake was cancelled.")
        blueprint = self.blueprint(lesson)
        draw = self.sampler.draw(blueprint.cells, self.bank.leftovers(lesson), seed=f"{lesson.id}:{attempt.attempt_no}")
        cells = {cell.index: cell for cell in blueprint.cells}
        accepted = {
            str(index): {**pick["question"], "id": cells[index].question_id, "question_id": pick["id"]}
            for index, pick in draw.picks.items()
        }
        return {
            "topic": lesson.topic,
            "user_context": lesson.user_context,
            "profile": LearnerProfile.of(lesson.owner.profile).as_dict(),
            "snapshot": lesson.config_snapshot,
            "settings": lesson.settings_snapshot,
            "assessment": lesson.assessment,
            "plan": lesson.plan,
            "blueprint": blueprint.to_json(),
            "exclusions": self.bank.exclusions(lesson),
            "accepted": accepted,
            "question_round": 0,
        }

    @staticmethod
    def blueprint(lesson: Lesson) -> LessonTestBlueprint:
        """The lesson's own, or (a lesson made before the blueprint) the one its old test implies, kept from now on."""
        if lesson.test_blueprint:
            return LessonTestBlueprint.from_json(lesson.test_blueprint)
        blueprint = LessonTestBlueprint.for_old_test((lesson.final_test or {}).get("questions"))
        lesson.record(test_blueprint=blueprint.to_json())
        return blueprint


class BankJoinNode(Node):
    name = "questions_join"

    def __init__(self, questions: QuestionRound | None = None):
        self.questions = questions or QuestionRound()

    def run(self, state: dict, ctx: FlowContext) -> dict:
        return self.questions.close(state, ctx).update


class BankBatchesRouter(Router):
    """After plan_batches: write every batch, or go straight on when every cell is already filled."""

    def __call__(self, state: dict):
        return QuestionSends.of(state) or "persist_attempt"


class BankRouter(Router):
    """After the join: write again what failed, plan the unfilled cells again, save the set, or give up."""

    def __init__(self, questions: QuestionRound | None = None):
        self.questions = questions or QuestionRound()

    def __call__(self, state: dict):
        match state.get("question_outcome"):
            case QuestionRound.COMPLETE:
                return "persist_attempt"
            case QuestionRound.REPLAN:
                return "plan_batches"
            case QuestionRound.SHORT:
                return "fail_attempt"
            case QuestionRound.RETRY:
                return QuestionSends.of(state, set(self.questions.retry_ids(state)))
            case _:
                return []


class PersistAttemptNode(Node):
    """The set becomes the attempt's questions and the attempt starts: `generating` → `in_progress`, in one step with
    the questions going on the record. If the attempt is gone (the retake was stopped), nothing is written."""

    name = "persist_attempt"

    def __init__(self, bank: QuestionBank | None = None):
        self.bank = bank or QuestionBank()

    def run(self, state: dict, ctx: FlowContext) -> dict:
        blueprint = LessonTestBlueprint.from_json(state["blueprint"])
        questions = [state["accepted"][str(cell.index)] for cell in blueprint.cells]
        with transaction.atomic():
            fresh = self.bank.add(
                state["lesson_id"], self.batch(ctx), [q for q in questions if not q.get("question_id")]
            )
            by_id = {q["id"]: q for q in fresh}
            snapshot = [by_id.get(q["id"], q) for q in questions]
            started = TestSubmission.objects.filter(
                pk=state["attempt_id"], status=TestSubmission.Status.GENERATING
            ).update(questions=snapshot, status=TestSubmission.Status.IN_PROGRESS, started_at=timezone.now())
            if not started:
                raise RunFailed("That retake was cancelled.")  # rolls the new rows back too
        return {}

    @staticmethod
    def batch(ctx: FlowContext) -> uuid.UUID | None:
        try:
            return uuid.UUID(str(ctx.run_id))
        except ValueError:
            return None


class FailAttemptNode(Node):
    name = "fail_attempt"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        raise RunFailed(state.get("error") or "The new questions could not be written.")
