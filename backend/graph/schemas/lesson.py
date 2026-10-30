"""Stage B content: the plan, the three content pages, and test questions (shared by the final test and the
practice sheet).

Flat models only: a question is one model with a `type` field and optional per-type fields checked by a
model_validator, not a union. Several providers handle unions poorly in structured-output mode.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from ..questions import QuestionTypes

PageKey = Literal["introduction", "core", "advanced"]
PAGE_KEYS: tuple[str, ...] = ("introduction", "core", "advanced")
QuestionType = Literal["mcq", "msq", "numerical", "short_answer", "long_answer"]
QUESTION_TYPES: tuple[str, ...] = ("mcq", "msq", "numerical", "short_answer", "long_answer")
Difficulty = Literal["easy", "basic", "standard", "difficult", "expert"]
DIFFICULTIES: tuple[str, ...] = ("easy", "basic", "standard", "difficult", "expert")
LevelName = Literal["beginner", "foundation", "proficient", "expert"]


class OutlineItem(BaseModel):
    concept: str = Field(description="The concept this part teaches. Not repeated on any other page.")
    heading: str
    notes: str = Field(description="What to cover and how, in 1-2 sentences.")


class PagePlan(BaseModel):
    key: PageKey
    title: str
    goals: list[str] = Field(description="2-4 learning goals for the page.")
    outline: list[OutlineItem] = Field(description="3-6 parts, in teaching order.")
    covers_gaps: list[str] = Field(description="Which of the learner's gaps this page addresses.")
    covers_prerequisites: list[str] = Field(
        description="Prerequisites taught on this page. The introduction must list every required prerequisite."
    )


class TypeMix(BaseModel):
    mcq: int = Field(ge=0)
    msq: int = Field(ge=0, description="Multiple select: choose all that apply.")
    numerical: int = Field(ge=0)
    short_answer: int = Field(ge=0)
    long_answer: int = Field(ge=0)

    def total(self) -> int:
        return self.mcq + self.msq + self.numerical + self.short_answer + self.long_answer


class DifficultyMix(BaseModel):
    easy: int = Field(ge=0)
    basic: int = Field(ge=0)
    standard: int = Field(ge=0)
    difficult: int = Field(ge=0)
    expert: int = Field(ge=0)

    def total(self) -> int:
        return self.easy + self.basic + self.standard + self.difficult + self.expert


class FinalTestSpec(BaseModel):
    question_count: int = Field(description="Between the configured minimum and maximum (usually 10-15).")
    type_mix: TypeMix = Field(description="Counts per question type; must add up to question_count.")
    difficulty_mix: DifficultyMix = Field(description="Counts per difficulty; must add up to question_count.")


class LessonPlan(BaseModel):
    title: str
    level: LevelName
    summary: str = Field(description="Two sentences: what the lesson covers and for whom.")
    pages: list[PagePlan] = Field(description="Exactly three: introduction, core, advanced.")
    final_test: FinalTestSpec


class WorkedExample(BaseModel):
    problem: str
    solution: str = Field(description="Step by step (Markdown).")


class Formula(BaseModel):
    latex: str = Field(description="LaTeX without surrounding $ signs.")
    explanation: str = Field(description="What each symbol means and when the formula applies.")


class CodeSnippet(BaseModel):
    language: str = Field(description='e.g. "python", "javascript", "typescript", "java", "cpp".')
    code: str
    explanation: str


class Callout(BaseModel):
    kind: Literal["note", "tip", "warning", "example"]
    text: str


class Section(BaseModel):
    id: str = Field(description='Stable id such as "s1"; unique within the page.')
    heading: str
    body: str = Field(description="The main explanation, in Markdown. LaTeX between $…$ or $$…$$.")
    key_points: list[str] = Field(default_factory=list)
    worked_examples: list[WorkedExample] = Field(default_factory=list)
    formulas: list[Formula] = Field(default_factory=list)
    code_snippets: list[CodeSnippet] = Field(default_factory=list)
    callouts: list[Callout] = Field(default_factory=list)


class PageContent(BaseModel):
    key: PageKey
    title: str
    sections: list[Section] = Field(description="3-6 sections following the plan's outline.")
    summary: str = Field(description="A short recap of the page.")


class Criterion(BaseModel):
    text: str = Field(description="One thing a good answer does, in a short sentence.")
    marks: int = Field(ge=1, description="Whole marks this thing is worth.")


class TestQuestion(BaseModel):
    """What a model writes for one question. Marks are not here: `MarksPolicy` sets them in code, and the right answer
    of a numerical question is computed from `answer_expr` (`QuestionFinisher`)."""

    id: str = Field(description='Unique id such as "t1".')
    type: QuestionType
    concept: str
    difficulty: Difficulty
    question: str = Field(description="Markdown; LaTeX between $…$ allowed.")
    # mcq and msq
    options: list[str] | None = Field(default=None, description="mcq: exactly 4 options. msq: 4 to 6 options.")
    correct_index: int | None = Field(default=None, description="mcq only: index of the correct option.")
    correct_indices: list[int] | None = Field(
        default=None, description="msq only: the indices of the correct options (at least 2, all different)."
    )
    # numerical
    answer_expr: str | None = Field(
        default=None,
        description="numerical only: the answer as a maths expression, for example sqrt(3)/2*10. Use + - * / **, "
        "parentheses, pi, e, and sqrt sin cos tan asin acos atan log (base 10) ln exp abs. Trigonometry is in radians.",
    )
    tolerance: float | None = Field(default=None, description="numerical only: accepted absolute error.")
    decimal_precision: int | None = Field(
        default=None, description="numerical only, 0 to 6: decimals of the answer (0 means a whole number)."
    )
    unit: str | None = Field(default=None, description="numerical only, may be empty.")
    # short_answer / long_answer
    model_answer: str | None = Field(default=None, description="short_answer and long_answer.")
    criteria: list[Criterion] | None = Field(
        default=None,
        description="short_answer and long_answer: what a good answer does, each worth whole marks that add up to the "
        "question's marks.",
    )

    @model_validator(mode="after")
    def _fields_for_type(self):
        if missing := QuestionTypes.get(self.type).missing_fields(self.model_dump()):
            raise ValueError(f"{self.type} question {self.id} needs {', '.join(missing)}")
        return self


class FinalTest(BaseModel):
    title: str = Field(default="Test your understanding")
    questions: list[TestQuestion]


def public_question(question: dict) -> dict:
    """Everything the learner may see before submitting: an allowlist per kind of question (`QuestionType`)."""
    return QuestionTypes.of(question).public(question)
