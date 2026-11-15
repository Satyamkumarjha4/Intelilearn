"""Rewrite only the quiz questions whose options a rule rejects, instead of regenerating the whole quiz.

A diagnostic quiz is 10 questions and its prerequisite quiz 5 more. A model sometimes repeats an option in one of them
(or writes "all of the above"); the validator then sent all fifteen back, and three failed attempts ended the lesson.
`OptionRepair` asks the diagnostic node's own models to rewrite the offending question alone: one call per question, no
second try, and at most `MAX_QUESTIONS` questions, because a quiz with more of them than that is poor as a whole and is
better regenerated. When a rewrite is not usable the question is left as it was, so the validator's verdict (and the
whole-quiz retry that follows it) is exactly what it was without the repair.
"""

import logging
from dataclasses import dataclass, field
from typing import ClassVar

from llm_registry.gateway import AllModelsFailed

from .context import FlowContext
from .prompts import RepairOptionsPrompt
from .schemas import DiagnosticQuestion, PrerequisiteQuestion
from .validators import TextRules

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RepairResult:
    bundle: dict
    #: ids of the questions that were rewritten and replaced
    repaired: list[str] = field(default_factory=list)
    #: ids of the offending questions that were left as they were (no usable rewrite, or too many to repair)
    unrepaired: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Kind:
    """One list of questions in the bundle, the schema of its questions and the fields a rewrite may not change."""

    key: str
    schema: type
    keep: tuple[str, ...]
    label: str


class OptionRepair:
    NODE_KEY: ClassVar[str] = "diagnostic.generate"  # the node's own models write the rewrite
    MAX_QUESTIONS: ClassVar[int] = 3
    KINDS: ClassVar[tuple[_Kind, ...]] = (
        _Kind("diagnostic", DiagnosticQuestion, ("id", "band", "concept"), "Question"),
        _Kind("prerequisite_questions", PrerequisiteQuestion, ("id", "prerequisite"), "Prerequisite question"),
    )

    def __init__(self, prompt: RepairOptionsPrompt | None = None):
        self.prompt = prompt or RepairOptionsPrompt()

    def repair(self, state: dict, ctx: FlowContext) -> RepairResult:
        bundle = state["bundle"]
        offenders = self.offenders(bundle)
        if not offenders:
            return RepairResult(bundle)
        if len(offenders) > self.MAX_QUESTIONS:
            return RepairResult(bundle, unrepaired=[question["id"] for _, _, question, _ in offenders])
        lists = {kind.key: list(bundle[kind.key]) for kind in self.KINDS}
        repaired, unrepaired = [], []
        for kind, index, question, problem in offenders:
            replacement = self.rewrite(state, ctx, kind, question, problem)
            if replacement is None:
                unrepaired.append(question["id"])
            else:
                lists[kind.key][index] = replacement
                repaired.append(question["id"])
        return RepairResult(bundle | lists, repaired, unrepaired) if repaired else RepairResult(bundle, [], unrepaired)

    def offenders(self, bundle: dict) -> list[tuple[_Kind, int, dict, str]]:
        """(kind, position, question, what is wrong) for every question whose options a rule rejects."""
        found = []
        for kind in self.KINDS:
            for index, question in enumerate(bundle[kind.key]):
                problems = TextRules.option_problems(f"{kind.label} {question['id']}", question["options"])
                if problems:
                    found.append((kind, index, question, " ".join(problems)))
        return found

    def rewrite(self, state: dict, ctx: FlowContext, kind: _Kind, question: dict, problem: str) -> dict | None:
        """The question with usable options, or None when no model answers or the answer still breaks the rule."""
        subject = {
            "topic": state["topic"],
            "user_context": state.get("user_context"),
            "profile": state.get("profile"),
            "question": question,
            "problem": problem,
        }
        try:
            output = ctx.invoke(state, self.NODE_KEY, self.prompt.messages(subject), schema=kind.schema).output
        except AllModelsFailed:
            logger.info("option repair: no model rewrote %s", question["id"])
            return None
        replacement = output.model_dump(mode="json") | {name: question[name] for name in kind.keep}
        if TextRules.option_problems(kind.label, replacement["options"]):
            logger.info("option repair: the rewrite of %s still breaks the option rules", question["id"])
            return None
        return replacement
