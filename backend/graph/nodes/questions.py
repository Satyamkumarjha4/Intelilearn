"""The questions pipeline: one set of steps for every graph that writes test questions (plan §9.3).

    plan_batches (code) → Send per batch → generate_questions (test.generate) → a join that decides, per round:
        retry the batches with problems | plan the cells still missing again | stop short | all cells are filled

`plan_batches` and `generate_questions` are real nodes, shared by the author stage and the retake (`question_bank`)
graph; each graph has its own join node, because a join also has its own work to wait for (the author stage's pages),
but they decide through the same `QuestionRound`. The cells come from the fixed `LessonTestBlueprint`, so what a
batch must contain does not depend on the model.
"""

from dataclasses import dataclass, field
from typing import ClassVar

from langgraph.types import Send

from lessons.models import Stage

from ..authoring import ContentWriter
from ..context import FlowContext, NodeBudget
from ..questions import BatchPlanner, Blueprints, QuestionDeduper, QuestionTypes
from .base import Node
from .branches import BranchBuilder


class QuestionSends:
    """The `Send`s that start (or restart) the writing of batches."""

    @staticmethod
    def of(state: dict, batch_ids: set[str] | None = None) -> list[Send]:
        sends = []
        for batch in state["question_plan"]["batches"]:
            if batch_ids is not None and batch["id"] not in batch_ids:
                continue
            feedback = list((state.get("feedback") or {}).get(f"batch:{batch['id']}") or [])
            sends.append(
                Send("generate_questions", BranchBuilder.of(state, key=batch["id"], item=batch, feedback=feedback))
            )
        return sends


class PlanBatchesNode(Node):
    """Splits the cells that have no question yet into batches. Names a new round every time it runs, so a batch id
    is never reused, and forgets what an earlier run knew about the batches it plans."""

    name = "plan_batches"
    stage = Stage.GENERATING_LESSON

    def run(self, state: dict, ctx: FlowContext) -> dict:
        blueprint = Blueprints.from_json(state["blueprint"])
        missing = blueprint.missing({int(index) for index in state.get("accepted") or {}})
        round_no = (state.get("question_round") or 0) + 1
        planner = BatchPlanner.from_settings(state.get("settings") or {}, capped=state.get("batch_capped", True))
        batches = planner.plan(missing, round_no)
        forget = {f"batch:{batch.id}": None for batch in batches}
        return {
            "question_round": round_no,
            "question_plan": {
                "round": round_no,
                "batches": [{"id": b.id, "cells": [cell.as_dict() for cell in b.cells]} for b in batches],
            },
            "attempts": forget,
            "feedback": forget,
            "question_outcome": "planned",
        }


class GenerateQuestionsNode(Node):
    """One batch, written in parallel with the others. The latest version is kept even with problems: the join decides
    whether to try again or to accept it."""

    name = "generate_questions"

    def run(self, state: dict, ctx: FlowContext) -> dict:
        batch = ContentWriter.batch_of(state["item"])
        questions, problems = ContentWriter(ctx).questions(state, batch, state.get("feedback"))
        key = f"batch:{batch.id}"
        return {
            "question_batches": {batch.id: {"questions": questions}},
            "feedback": {key: problems},
            "attempts": {key: 1},
        }


@dataclass(frozen=True)
class RoundResult:
    outcome: str
    update: dict = field(default_factory=dict)
    retry: tuple[str, ...] = ()  # the batches to write again


class QuestionRound:
    """What a join does with the batches that came back, in one place for every graph.

    `retry`: a batch has problems and attempts left. `replan`: some cells are still unfilled and rounds are left.
    `short`: unfilled cells and no rounds left, so the test cannot be built. `complete`: every cell has a question.
    `pending`: a batch of this round has not reported yet, so there is nothing to decide.

    A lesson test is a fixed blueprint and must be whole (`strict`). A quick quiz keeps what it has and warns when a few
    cells could not be filled: a quiz of 9 questions of 10 is better than none (the old rule that an optional check
    never fails a lesson); only a quiz with no question at all is `short`.
    """

    PENDING, RETRY, REPLAN, SHORT, COMPLETE = "pending", "retry", "replan", "short", "complete"
    NODE_KEY: ClassVar[str] = "test.generate"

    def __init__(self, deduper: QuestionDeduper | None = None, *, strict: bool = True):
        self.deduper = deduper or QuestionDeduper()
        self.strict = strict

    def retry_ids(self, state: dict) -> tuple[str, ...]:
        budget = NodeBudget.of(state, self.NODE_KEY).max_attempts
        feedback, attempts = state.get("feedback") or {}, state.get("attempts") or {}
        return tuple(
            batch["id"]
            for batch in state["question_plan"]["batches"]
            if feedback.get(f"batch:{batch['id']}") and attempts.get(f"batch:{batch['id']}", 0) < budget
        )

    def close(self, state: dict, ctx: FlowContext) -> RoundResult:
        plan, written = state["question_plan"], state.get("question_batches") or {}
        if any(batch["id"] not in written for batch in plan["batches"]):
            return RoundResult(self.PENDING, {"question_outcome": self.PENDING})
        if retry := self.retry_ids(state):
            feedback = state["feedback"]
            for batch_id in retry:
                ctx.events({"type": "attempt", "node": f"generate_questions:{batch_id}",
                            "reason": feedback[f"batch:{batch_id}"][0]})  # fmt: skip
            return RoundResult(self.RETRY, {"question_outcome": self.RETRY}, retry)
        accepted, warnings = self._accept(state, ctx)
        blueprint = Blueprints.from_json(state["blueprint"])
        missing = blueprint.missing({int(index) for index in accepted})
        update = {"accepted": accepted, "warnings": warnings}
        if not missing:
            return RoundResult(self.COMPLETE, update | {"question_outcome": self.COMPLETE})
        if plan["round"] < NodeBudget.of(state, self.NODE_KEY).max_attempts:
            return RoundResult(self.REPLAN, update | {"question_outcome": self.REPLAN})
        if not self.strict and accepted:
            kept = ctx.warn(
                f"The quiz has {len(accepted)} of {len(blueprint.cells)} questions: the rest could not be written."
            )
            return RoundResult(self.COMPLETE, update | {"warnings": warnings + kept, "question_outcome": self.COMPLETE})
        numbers = ", ".join(str(cell.index + 1) for cell in missing)
        return RoundResult(
            self.SHORT,
            update | {
                "question_outcome": self.SHORT,
                "error": f"The test could not be filled: no usable question for cell(s) {numbers} after "
                         f"{plan['round']} rounds.",
                "failed_node": "plan_batches",
                "retry_keys": [],
                "question_round": 0,
                "accepted": {},
            },
        )  # fmt: skip

    def _accept(self, state: dict, ctx: FlowContext) -> tuple[dict, list[str]]:
        """The questions that fill a cell: of the cell's type and difficulty, usable (a numerical question has its
        answer, a criteria question criteria that add up…) and new. Problems that do not stop a question from being
        used are reported as a warning instead (the old rule: an optional check never fails a lesson)."""
        accepted = dict(state.get("accepted") or {})
        candidates, warnings = [], []
        for batch in state["question_plan"]["batches"]:
            problems = (state.get("feedback") or {}).get(f"batch:{batch['id']}") or []
            if problems:
                warnings += ctx.warn(f"Some questions were kept despite: {'; '.join(problems[:3])}")
            for cell, question in zip(
                batch["cells"], state["question_batches"][batch["id"]]["questions"], strict=False
            ):
                if self._fills(cell, question):
                    candidates.append((cell, question))
        asked = [*(state.get("exclusions") or []), *(q["question"] for q in accepted.values())]
        fresh = {id(q) for q in self.deduper.fresh([q for _, q in candidates], asked).kept}
        accepted |= {str(cell["index"]): question for cell, question in candidates if id(question) in fresh}
        return accepted, warnings

    @staticmethod
    def _fills(cell: dict, question: dict) -> bool:
        if (question["type"], question["difficulty"]) != (cell["type"], cell["difficulty"]):
            return False
        return not QuestionTypes.of(question).problems(question, question["id"])
