"""Mastery path prompt: one of the three study sheets."""

from ..questions import QuestionTypes
from ..schemas.lesson import QUESTION_TYPES
from .base import Prompt

STUDY_INSTRUCTIONS = {
    "cheat_sheet": """Write a CHEAT SHEET: dense, scannable notes that fit on one or two screens.
- For quantitative topics: formulas (kind "formula", LaTeX in "formula", every symbol in "variables") with when
  to use each.
- For theoretical topics: key terms, facts and one-line rules.
- 3-6 sections, 3-8 items each, one or two lines per item. No padding.""",
    "revision_sheet": """Write a REVISION SHEET: longer notes that cover EVERY subtopic of the topic.
- 4-10 subtopics, each with a real paragraph summary, 3-6 key points, worked examples where useful, and the
  common mistakes learners make.
- End with a few final tips for revising.""",
    "practice_sheet": """Write a PRACTICE SHEET of 15-25 questions, ordered from easy to expert (easy, basic, standard,
difficult, expert).
- Mix at least 3 types. Use only the types that suit the topic. How to write each, and what it is worth (marks are
  set by the system, never by you):
{guidance}
- Every question has a concept and a difficulty. Ids "t1", "t2"…""",
}


class StudyMaterialPrompt(Prompt):
    """Subject also carries `kind` (the sheet to write), `concepts` (what it must cover) and, when the sheet is asked
    for from a lesson or a topic, `grounding` (graph/grounding.py): what it rests on and who it is for. Without a
    grounding this is the mastery path's wording, for a learner who aced the quick check."""

    MASTERED = """You write study material for a learner who ALREADY KNOWS this topic well (they aced a \
diagnostic quiz). Consolidate and sharpen; don't teach from scratch."""
    FROM_A_LESSON = """You write study material for a learner who has just studied the lesson described below. The \
sheet must follow that lesson: use its terms and notation, cover what it teaches, and add nothing it does not \
teach. Consolidate and sharpen; don't teach from scratch."""
    FROM_A_LEVEL = """You write study material for a learner at the level given below. Pitch it for that level: a \
Beginner needs the basics in plain words, an Expert needs it dense and exam-ready. Write for what they are likely to \
know; don't assume more."""

    @staticmethod
    def instructions(kind: str) -> str:
        return STUDY_INSTRUCTIONS[kind].replace("{guidance}", QuestionTypes.guidance(QUESTION_TYPES))

    def opening(self, subject: dict) -> str:
        grounding = subject.get("grounding")
        if grounding is None or grounding["audience"] == "mastered":
            return self.MASTERED
        return self.FROM_A_LESSON if grounding["kind"] == "lesson" else self.FROM_A_LEVEL

    def system(self, subject: dict) -> str:
        return f"""{self.opening(subject)}

{self.instructions(subject["kind"])}

Use Markdown; LaTeX between $…$ for inline maths (in Markdown fields). Be accurate and exam-ready.
{self.language_rule(subject.get("profile"))}"""

    def user(self, subject: dict) -> str:
        grounding = subject.get("grounding")
        return f"""{self.topic_text(subject)}

The learner:
{self.learner_text(subject.get("profile"))}
{self.grounding_text(grounding)}
{self.concepts_text(subject, grounding)}"""

    @staticmethod
    def concepts_text(subject: dict, grounding: dict | None) -> str:
        concepts = subject.get("concepts") or []
        if grounding is not None and not concepts:
            return ""  # nothing to cover but the topic itself
        return f"\nKey concepts that must be covered: {Prompt.to_json(concepts)}"

    @staticmethod
    def grounding_text(grounding: dict | None) -> str:
        """What the sheet rests on, as the user message tells it: the lesson, the quiz's findings, or the level."""
        if grounding is None:
            return ""
        lines = []
        if grounding["level"]:
            lines.append(f"The learner's level: {grounding['level']}.")
        if lesson := grounding.get("lesson"):
            pages = "\n".join(f"- {page['title']}: {'; '.join(page['headings'])}" for page in lesson["pages"])
            lines.append(f'The lesson they studied: "{lesson["title"]}". {lesson["summary"]}\nIts pages:\n{pages}')
        if grounding["known"]:
            lines.append(f"What their quick check showed they know: {'; '.join(grounding['known'])}.")
        if grounding["gaps"]:
            lines.append(f"What they found hard: {'; '.join(grounding['gaps'])}. Give these extra care.")
        return ("\n" + "\n".join(lines)) if lines else ""
