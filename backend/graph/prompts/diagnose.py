"""Stage A prompts: the diagnostic bundle, its optional reviewer, and the learner assessment."""

from ..schemas.diagnostic import BANDS
from ..shapes import LessonShapes
from .base import Prompt

BAND_MEANINGS = {
    "basic": "vocabulary and the core idea; anyone who has met the topic can answer",
    "easy_moderate": "direct application of the core idea",
    "moderate": "standard problems and typical usage",
    "moderate_hard": "edge cases, trade-offs, analysis",
    "hard": "expert level: only answerable with real mastery, NOT by general knowledge, elimination or wording cues",
}


class DiagnosticPrompt(Prompt):
    """Subject may say `include_prerequisites: False` (the calibration quiz uses the diagnostic's questions as its pool
    and
    has no prerequisite half)."""

    def system(self, subject: dict) -> str:
        settings = subject["settings"]
        per_band = settings.get("diagnostic_questions_per_band", 2)
        prereqs = settings.get("prerequisite_question_count", 5)
        bands = "\n".join(f'- "{band}": {BAND_MEANINGS[band]}' for band in BANDS)
        with_prerequisites = subject.get("include_prerequisites", True)
        opening = "a short diagnostic quiz that reveals what a learner already knows about a topic" + (
            ", plus a prerequisite quiz." if with_prerequisites else "."
        )
        closing = (
            f"""PREREQUISITE QUIZ: the {prereqs} most important concepts a learner must know BEFORE this topic (not
            parts of \
the topic itself), each with "why_needed", and exactly one "basic" question per prerequisite whose \
"prerequisite" field equals that prerequisite's name exactly. Ids: diagnostic "q1".., prerequisite "p1".."""
            if with_prerequisites
            else 'There is no prerequisite quiz this time: return empty lists for "prerequisites" and '
            '"prerequisite_questions". Ids: "q1"..'
        )
        return f"""You are an expert assessment designer. You write {opening}

DIAGNOSTIC QUIZ: exactly {per_band * len(BANDS)} multiple-choice questions, exactly {per_band} per band, \
easiest band first:
{bands}

Rules:
- Every question probes a DIFFERENT concept of the topic (set "concept"; no two alike). Together they sample the \
whole topic.
- Questions are independent: none depends on, or reveals, the answer of another.
- Exactly 4 options, exactly one correct. Options are plausible, similar in length and style, and all different. \
Never use "all of the above", "none of the above" or "both A and B".
- The correct option's position varies across questions.
- "hard" questions must not be answerable by elimination, general knowledge, or cues in the wording.
- Every question has a 1-3 sentence explanation of the correct answer.
- The learner will also see an "I don't know" option; don't add it yourself.
- Use Markdown for code (`inline`) and LaTeX between $…$ for maths.

{closing}

{self.language_rule(subject.get("profile"))}"""

    def user(self, subject: dict) -> str:
        return f"""{self.topic_text(subject)}

The learner:
{self.learner_text(subject.get("profile"))}

Write the diagnostic bundle."""


class DiagnosticReviewPrompt(Prompt):
    """Subject also carries `bundle`."""

    def system(self, subject: dict) -> str:
        return """You review diagnostic quizzes. Report only real problems:
- a question that depends on or reveals another question's answer;
- a question whose band is wrong (for example a "hard" question answerable from the wording or by elimination,
  or a "basic" question that needs expert knowledge);
- a wrong or ambiguous correct answer.
Return an empty issues list when the quiz is fine."""

    def user(self, subject: dict) -> str:
        quiz = [
            {k: q[k] for k in ("id", "band", "concept", "question", "options", "correct_index")}
            for q in subject["bundle"]["diagnostic"]
        ]
        return f"{self.topic_text(subject)}\n\nQuiz:\n{self.to_json(quiz)}"


class PlanPrerequisitesPrompt(Prompt):
    """Subject carries the `assessment` (a Beginner's, from the self-rating) and the level's shape."""

    def system(self, subject: dict) -> str:
        return f"""You plan what a complete beginner should learn BEFORE a topic, for the writers of their lesson. \
The learner took no quiz: they only told us they are new to the topic.

List 3 to 6 prerequisites, most fundamental first. Each has a short "name" (a concept, not a sentence) and a \
"why_needed" sentence that says where the topic relies on it.

Rules:
- Prerequisites are concepts to know BEFORE the topic, never parts of the topic itself.
- Only what a learner who is new here may really lack. Do not list things everyone at school age knows.
- Fewer is better than padding; never more than 6.
{self.language_rule(subject.get("profile"))}"""

    def user(self, subject: dict) -> str:
        return f"""{self.topic_text(subject)}

The learner:
{self.learner_text(subject.get("profile"))}

What the lesson will be like:
{LessonShapes.of(subject["assessment"]).describe()}"""


class AssessLearnerPrompt(Prompt):
    """Subject also carries `diagnostic_questions` and `prerequisite_questions`."""

    def system(self, subject: dict) -> str:
        levels = "\n".join(f"  {shape.level.value}: {shape.summary}" for shape in LessonShapes.all())
        return f"""You assess a learner from their quiz results and profile, for the writers of their lesson.
- level: beginner (knows almost nothing), foundation (knows some basics), proficient (solid on most of it), expert
  (could teach it). Each level gets a different lesson, so choose the one whose lesson would suit them:
{levels}
- known_concepts / gaps: from the per-concept results. Wrong answers are gaps; "I don't know" is honest, not bad.
- start_point: where the core-concepts page should begin, given what they already know.
- author_notes: concrete guidance on tone, depth, pacing, examples and analogies for this learner.
- prerequisites_to_cover: copy the given list EXACTLY; you may not add or remove items.
- confidence: lower it when the results look inconsistent (hard right but basic wrong suggests guessing)."""

    def user(self, subject: dict) -> str:
        result = subject["diagnostic_result"]
        prereq_result = subject.get("prerequisite_result")
        to_cover = [p["name"] for p in subject.get("prerequisites_to_cover") or []]
        consistency = "consistent" if result["consistent"] else "INCONSISTENT (possible guessing)"
        text = f"""{self.topic_text(subject)}

The learner:
{self.learner_text(subject.get("profile"))}

Diagnostic: {result["correct"]}/{result["total"]} correct, {result["dont_know"]} "I don't know". \
Results look {consistency}.
{self.results_text(subject["diagnostic_questions"], result)}
"""
        if prereq_result:
            text += f"\nPrerequisite quiz: {prereq_result['correct']}/{prereq_result['total']} correct.\n"
            text += self.results_text(subject["prerequisite_questions"], prereq_result) + "\n"
        return text + f"\nprerequisites_to_cover (copy exactly): {self.to_json(to_cover)}"

    @staticmethod
    def results_text(questions: list[dict], result: dict) -> str:
        rows = []
        for q in questions:
            label = q.get("band") or "prerequisite"
            concept = q.get("concept") or q.get("prerequisite")
            rows.append(
                f"- [{label}] {concept}: {'correct' if result['per_question'][q['id']] else 'wrong / did not know'}"
            )
        return "\n".join(rows)
