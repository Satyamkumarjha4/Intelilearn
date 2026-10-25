"""Stage B content: the plan, the three content pages, and test questions (shared by the final test and the
practice sheet).

Flat models only: a question is one model with a `type` field and optional per-type fields checked by a
model_validator, not a union. Several providers handle unions poorly in structured-output mode.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

PageKey = Literal["introduction", "core", "advanced"]
PAGE_KEYS: tuple[str, ...] = ("introduction", "core", "advanced")
QuestionType = Literal["mcq", "numerical", "short_answer", "long_answer", "code"]
QUESTION_TYPES: tuple[str, ...] = ("mcq", "numerical", "short_answer", "long_answer", "code")
Difficulty = Literal["easy", "medium", "hard"]
DIFFICULTIES: tuple[str, ...] = ("easy", "medium", "hard")


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
    numerical: int = Field(ge=0)
    short_answer: int = Field(ge=0)
    long_answer: int = Field(ge=0)
    code: int = Field(ge=0)

    def total(self) -> int:
        return self.mcq + self.numerical + self.short_answer + self.long_answer + self.code


class DifficultyMix(BaseModel):
    easy: int = Field(ge=0)
    medium: int = Field(ge=0)
    hard: int = Field(ge=0)

    def total(self) -> int:
        return self.easy + self.medium + self.hard


class FinalTestSpec(BaseModel):
    question_count: int = Field(description="Between the configured minimum and maximum (usually 10-15).")
    type_mix: TypeMix = Field(description="Counts per question type; must add up to question_count.")
    difficulty_mix: DifficultyMix = Field(description="Counts per difficulty; must add up to question_count.")


class LessonPlan(BaseModel):
    title: str
    level: Literal["novice", "beginner", "intermediate", "advanced"]
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


class CodeTestCase(BaseModel):
    input: str
    expected_output: str


class TestQuestion(BaseModel):
    id: str = Field(description='Unique id such as "t1".')
    type: QuestionType
    concept: str
    difficulty: Difficulty
    marks: int = Field(ge=1, le=20)
    question: str = Field(description="Markdown; LaTeX between $…$ allowed.")
    # mcq
    options: list[str] | None = Field(default=None, description="mcq only: exactly 4 options.")
    correct_index: int | None = Field(default=None, description="mcq only: index of the correct option.")
    # numerical
    answer: float | None = Field(default=None, description="numerical only.")
    tolerance: float | None = Field(default=None, description="numerical only: accepted absolute error.")
    unit: str | None = Field(default=None, description="numerical only, may be empty.")
    # short_answer / long_answer
    model_answer: str | None = Field(default=None, description="short_answer, long_answer and code.")
    key_points: list[str] | None = Field(default=None, description="short_answer: points a good answer makes.")
    rubric: list[str] | None = Field(default=None, description="long_answer: marking criteria.")
    # code
    language: str | None = Field(default=None, description="code only.")
    starter_code: str | None = Field(default=None, description="code only.")
    reference_solution: str | None = Field(default=None, description="code only.")
    test_cases: list[CodeTestCase] | None = Field(default=None, description="code only: 1-5 cases.")

    @model_validator(mode="after")
    def _fields_for_type(self):
        missing = []
        if self.type == "mcq":
            if not self.options or len(self.options) != 4:
                missing.append("options (exactly 4)")
            if self.correct_index is None or not 0 <= self.correct_index <= 3:
                missing.append("correct_index (0-3)")
        elif self.type == "numerical":
            if self.answer is None:
                missing.append("answer")
            if self.tolerance is None or self.tolerance < 0:
                missing.append("tolerance (>= 0)")
        elif self.type == "short_answer":
            if not self.model_answer:
                missing.append("model_answer")
            if not self.key_points:
                missing.append("key_points")
        elif self.type == "long_answer":
            if not self.model_answer:
                missing.append("model_answer")
            if not self.rubric:
                missing.append("rubric")
        elif self.type == "code":
            for name in ("language", "reference_solution"):
                if not getattr(self, name):
                    missing.append(name)
            if not self.test_cases:
                missing.append("test_cases")
        if missing:
            raise ValueError(f"{self.type} question {self.id} needs {', '.join(missing)}")
        return self


class FinalTest(BaseModel):
    title: str = Field(default="Test your understanding")
    questions: list[TestQuestion]


# Everything the learner may see before submitting, per type.
PUBLIC_QUESTION_FIELDS = ("id", "type", "concept", "difficulty", "marks", "question", "options", "unit", "language",
                          "starter_code")  # fmt: skip


def public_question(question: dict) -> dict:
    return {key: question.get(key) for key in PUBLIC_QUESTION_FIELDS if question.get(key) is not None}
