"""Mastery path: the three study sheets. Rendered by fixed frontend templates, never by generated code."""

from typing import Literal

from pydantic import BaseModel, Field

from .lesson import TestQuestion, WorkedExample


class Variable(BaseModel):
    symbol: str = Field(description="LaTeX for the symbol, without $ signs.")
    meaning: str


class CheatItem(BaseModel):
    label: str = Field(description='Short name, e.g. "Binary search loop invariant".')
    kind: Literal["formula", "rule", "term", "fact", "pattern"]
    content: str = Field(description="One or two lines of Markdown. LaTeX between $…$.")
    formula: str = Field(default="", description="LaTeX without $ signs; empty unless kind is formula.")
    variables: list[Variable] = Field(default_factory=list, description="For formulas: what each symbol means.")
    when_to_use: str = Field(default="", description="One line.")


class CheatSection(BaseModel):
    heading: str
    items: list[CheatItem] = Field(description="3-8 items.")


class CheatSheet(BaseModel):
    title: str
    summary: str = Field(description="One or two sentences.")
    sections: list[CheatSection] = Field(description="3-6 sections. The whole sheet fits on one or two screens.")


class RevisionSubtopic(BaseModel):
    title: str
    summary: str = Field(description="A paragraph of Markdown.")
    key_points: list[str] = Field(description="3-6 points.")
    worked_examples: list[WorkedExample] = Field(default_factory=list)
    common_mistakes: list[str] = Field(default_factory=list)


class RevisionSheet(BaseModel):
    title: str
    overview: str
    subtopics: list[RevisionSubtopic] = Field(description="Every subtopic of the topic, 4-10 of them.")
    final_tips: list[str] = Field(default_factory=list)


class PracticeSheet(BaseModel):
    title: str
    instructions: str
    questions: list[TestQuestion] = Field(description="15-25 questions of mixed types, easiest first.")


MATERIAL_SCHEMAS: dict[str, type[BaseModel]] = {
    "cheat_sheet": CheatSheet,
    "revision_sheet": RevisionSheet,
    "practice_sheet": PracticeSheet,
}
