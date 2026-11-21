"""Mastery path: the three study sheets. Rendered by fixed frontend templates, never by generated code."""

from typing import ClassVar, Literal

from pydantic import BaseModel, Field

from .lesson import TestQuestion, WorkedExample
from .nullable import NullableFields


class Variable(BaseModel):
    symbol: str = Field(description="LaTeX for the symbol, without $ signs.")
    meaning: str


class CheatItem(NullableFields):
    label: str = Field(description='Short name, e.g. "Binary search loop invariant".')
    kind: Literal["formula", "rule", "term", "fact", "pattern"]
    content: str = Field(description="One or two lines of Markdown. LaTeX between $…$.")
    formula: str | None = Field(description="LaTeX without $ signs; empty unless kind is formula.")
    variables: list[Variable] | None = Field(description="For formulas: what each symbol means; empty otherwise.")
    when_to_use: str | None = Field(description="One line, or empty.")

    NULL_MEANS: ClassVar = {"formula": str, "variables": list, "when_to_use": str}


class CheatSection(BaseModel):
    heading: str
    items: list[CheatItem] = Field(description="3-8 items.")


class CheatSheet(BaseModel):
    title: str
    summary: str = Field(description="One or two sentences.")
    sections: list[CheatSection] = Field(description="3-6 sections. The whole sheet fits on one or two screens.")


class RevisionSubtopic(NullableFields):
    title: str
    summary: str = Field(description="A paragraph of Markdown.")
    key_points: list[str] = Field(description="3-6 points.")
    worked_examples: list[WorkedExample] | None = Field(description="Worked examples, or an empty list.")
    common_mistakes: list[str] | None = Field(description="Common mistakes, or an empty list.")

    NULL_MEANS: ClassVar = {"worked_examples": list, "common_mistakes": list}


class RevisionSheet(NullableFields):
    title: str
    overview: str
    subtopics: list[RevisionSubtopic] = Field(description="Every subtopic of the topic, 4-10 of them.")
    final_tips: list[str] | None = Field(description="Closing tips, or an empty list.")

    NULL_MEANS: ClassVar = {"final_tips": list}


class PracticeSheet(BaseModel):
    title: str
    instructions: str
    questions: list[TestQuestion] = Field(description="15-25 questions of mixed types, easiest first.")


MATERIAL_SCHEMAS: dict[str, type[BaseModel]] = {
    "cheat_sheet": CheatSheet,
    "revision_sheet": RevisionSheet,
    "practice_sheet": PracticeSheet,
}
