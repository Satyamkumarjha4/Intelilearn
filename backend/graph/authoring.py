"""Writing the lesson's content: one object that asks a model for a page, a batch of test questions or a widget and
checks the result.

The same writer serves the first attempt (the write_* nodes) and a fix after the alignment judge (fix_item), so a
fixed item is held to exactly the rules of a fresh one.
"""

from .context import FlowContext
from .prompts import GenerateInteractivePrompt, WritePagePrompt, WriteQuestionsPrompt, WriteQuizQuestionsPrompt
from .questions import Batch, Cell, LessonTestBlueprint, QuestionFinisher
from .sanitizer import CodeSanitizer
from .schemas import InteractiveComponent, PageContent, QuestionBatch, component_name
from .validators import PageValidator, QuestionBatchValidator


class ContentWriter:
    def __init__(self, ctx: FlowContext, sanitizer: CodeSanitizer | None = None):
        self.ctx = ctx
        self.sanitizer = sanitizer or CodeSanitizer()

    def page(self, data: dict, key: str, feedback: list[str] | None) -> tuple[dict, list[str]]:
        """→ (the page, the validator's problems with it). The page is returned even when it has problems."""
        plan_page = next(p for p in data["plan"]["pages"] if p["key"] == key)
        messages = WritePagePrompt().messages(data | {"page_plan": plan_page}, feedback)
        output = self.ctx.invoke(data, "page.generate", messages, schema=PageContent).output
        page = output.model_dump(mode="json") | {"key": key}
        return page, PageValidator(self.ctx.sandbox).validate(page, plan_page=plan_page)

    def questions(self, data: dict, batch: Batch, feedback: list[str] | None) -> tuple[list[dict], list[str]]:
        """The questions for a batch's cells → (the questions in cell order, the problems with them). The marks, the
        ids and the answer of a numerical question are set here by code, never taken from the model, and the questions
        come back even with problems: the join decides whether to try again."""
        cells = batch.cells
        prompt = WriteQuizQuestionsPrompt() if data.get("quiz") else WriteQuestionsPrompt()
        messages = prompt.messages(data | {"batch": self.batch_json(batch)}, feedback)
        output = self.ctx.invoke(data, "test.generate", messages, schema=QuestionBatch).output
        written = [question.model_dump(mode="json") for question in output.questions]
        for cell, question in zip(cells, written, strict=False):
            question["id"] = cell.question_id
        finished, finishing = QuestionFinisher().finish(written)
        problems = QuestionBatchValidator(self.ctx.sandbox).validate(finished, cells=cells)
        return finished, list(dict.fromkeys(finishing + problems))

    def question(self, data: dict, question_id: str, feedback: list[str] | None) -> tuple[dict, list[str]]:
        """One question of the test written again (a fix after the review): the batch is its own cell, and the other
        questions of the test are given as ones not to repeat."""
        cell = next(c for c in LessonTestBlueprint.from_json(data["blueprint"]).cells if c.question_id == question_id)
        asked = [q["question"] for q in data["final_test"]["questions"]]
        subject = data | {"exclusions": [*(data.get("exclusions") or []), *asked]}
        (question,), problems = self.questions(subject, Batch(f"fix-{question_id}", (cell,)), feedback)
        return question, problems

    @staticmethod
    def batch_json(batch: Batch) -> dict:
        return {"id": batch.id, "cells": [cell.as_dict() for cell in batch.cells]}

    @staticmethod
    def batch_of(data: dict) -> Batch:
        """The batch a `Send` carries (stored as plain JSON in the state)."""
        return Batch(data["id"], tuple(Cell(**cell) for cell in data["cells"]))

    def component(self, data: dict, spec: dict, feedback: list[str] | None) -> tuple[dict, list[str]]:
        """interactive.generate, then the sandbox's static and security check → (component, problems)."""
        name = component_name(spec["id"])
        section = self.section(data, spec)
        subject = data | {"spec": spec, "component_name": name, "section": section}
        messages = GenerateInteractivePrompt().messages(subject, feedback)
        output: InteractiveComponent = self.ctx.invoke(
            data, "interactive.generate", messages, schema=InteractiveComponent
        ).output
        tsx = self.sanitizer.sanitize(output.tsx)
        check = self.ctx.sandbox.check_code(tsx, required=[name])
        component = {
            "spec_id": spec["id"], "component_name": name, "tsx": tsx, "page": spec["page"],
            "anchor": spec["anchor_section"], "kind": spec["kind"], "purpose": spec["purpose"],
        }  # fmt: skip
        return component, list(check.errors)

    @staticmethod
    def section(data: dict, spec: dict) -> dict | None:
        page = (data.get("pages") or {}).get(spec["page"]) or {}
        return next((s for s in page.get("sections", []) if s["id"] == spec["anchor_section"]), None)
