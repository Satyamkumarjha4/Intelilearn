"""Mastery path prompt: one of the three study sheets."""

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
    "practice_sheet": """Write a PRACTICE SHEET of 15-25 questions, ordered easy → medium → hard.
- Mix at least 3 types: mcq (exactly 4 options + correct_index), numerical (answer + tolerance + unit),
  short_answer (model_answer + key_points), long_answer (model_answer + rubric), code (language, starter_code,
  reference_solution, 1-5 test_cases). Use only the types that suit the topic.
- Every question has a concept, difficulty and marks. Ids "t1", "t2"…""",
}


class StudyMaterialPrompt(Prompt):
    """Subject also carries `kind` (the sheet to write) and `concepts` (what it must cover)."""

    def system(self, subject: dict) -> str:
        return f"""You write study material for a learner who ALREADY KNOWS this topic well (they aced a \
diagnostic quiz). Consolidate and sharpen; don't teach from scratch.

{STUDY_INSTRUCTIONS[subject["kind"]]}

Use Markdown; LaTeX between $…$ for inline maths (in Markdown fields). Be accurate and exam-ready.
{self.language_rule(subject.get("profile"))}"""

    def user(self, subject: dict) -> str:
        return f"""{self.topic_text(subject)}

The learner:
{self.learner_text(subject.get("profile"))}

Key concepts that must be covered: {self.to_json(subject.get("concepts") or [])}"""
