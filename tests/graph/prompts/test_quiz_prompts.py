"""Unit under test: `graph.prompts.WriteQuizQuestionsPrompt` and the pool variant of `DiagnosticPrompt`: what the model
is
told when it writes the questions of a quick quiz and the questions of a calibration walk.

Why: a quiz has no lesson plan to lean on. A topic quiz must be told the learner's level; a quiz from lessons must be
told what each lesson covered, in a few lines built from its plan, and only for the lessons its batch is about, or a
call would carry ten lessons' worth of text. The calibration pool must not ask for the prerequisite half the diagnostic
normally writes, which would be paid for and thrown away.

Use cases:
- the quiz prompt lists one line per cell in order with type, difficulty and marks, and the instructions for those types
  only
- a topic quiz is told the topic and the learner's level
- a quiz from lessons names the lesson each cell is about, gives the summary and level of the lessons of this batch
  only, and tells the model to ask about nothing else
- a quiz from lessons lists, under each lesson of the batch, the concepts a question about it may name, to be copied
  exactly; a lesson with no concepts in its summary, and a topic quiz, list none and are not asked for any
- the questions already asked are given as ones not to repeat, shortened and capped
- a programming topic asked for short or long answers is told that the answer may be code, with the language to name
- the rejected-attempt feedback and the language rule are there, as in every prompt
- the diagnostic prompt for a pool asks for the two questions per band and no prerequisite quiz; the normal one asks
  for both
"""

from graph.prompts import DiagnosticPrompt, WriteQuizQuestionsPrompt

CELLS = [
    {"index": 0, "type": "mcq", "difficulty": "easy", "marks": 1, "source": "a"},
    {"index": 1, "type": "msq", "difficulty": "basic", "marks": 2, "source": "a"},
    {"index": 2, "type": "mcq", "difficulty": "expert", "marks": 2, "source": "b"},
]
QUIZ = {
    "level": "foundation",
    "code_format": False,
    "sources": {
        "a": {
            "title": "Binary search",
            "level": "beginner",
            "summary": "SUMMARY-A: halving the range.",
            "concepts": ["Halving the range", "Time complexity"],
        },
        "b": {"title": "Sorting", "level": "expert", "summary": "SUMMARY-B: merge sort.", "concepts": ["Merge sort"]},
        "c": {"title": "Graphs", "level": "proficient", "summary": "SUMMARY-C: BFS and DFS."},
    },
}


def subject(**fields) -> dict:
    base = {
        "topic": "Algorithms", "profile": {"preferred_language": "en"}, "exclusions": [],
        "quiz": QUIZ, "batch": {"id": "b1-1", "cells": CELLS},
    }  # fmt: skip
    return base | fields


def texts(**fields):
    system, user = (m.content for m in WriteQuizQuestionsPrompt().messages(subject(**fields)))
    return system, user


class TestTheQuizPrompt:
    def test_one_line_per_cell_in_order_and_the_instructions_for_those_types_only(self):
        system, _ = texts()

        assert "exactly 3 questions" in system
        lines = [line for line in system.splitlines() if line[:2] in ("1.", "2.", "3.")]
        assert [line.split(",")[0].split(". ")[1] for line in lines] == ["mcq", "msq", "mcq"]
        assert "msq" in system and "numerical" not in system

    def test_the_marks_are_told_but_never_chosen_by_the_model(self):
        system, _ = texts()

        assert "worth 2 marks" in system and "never by you" in system

    def test_a_topic_quiz_is_told_the_topic_and_the_learners_level(self):
        cells = [{**c, "source": ""} for c in CELLS]
        _, user = texts(
            quiz={"level": "proficient", "code_format": False, "sources": {}}, batch={"id": "b", "cells": cells}
        )

        assert "Algorithms" in user and "proficient" in user

    def test_a_quiz_from_lessons_names_the_lesson_of_each_cell(self):
        system, _ = texts()

        assert 'about "Binary search"' in system and 'about "Sorting"' in system

    def test_only_the_lessons_of_this_batch_are_summarised(self):
        _, user = texts()

        assert "SUMMARY-A" in user and "SUMMARY-B" in user
        assert "SUMMARY-C" not in user and "Graphs" not in user

    def test_each_lesson_is_given_with_its_own_level(self):
        _, user = texts()

        assert "Binary search" in user and "beginner" in user and "expert" in user

    def test_the_model_is_told_to_ask_about_the_lessons_concepts_only(self):
        system, _ = texts()

        assert "only" in system and "lesson" in system

    def test_the_concepts_a_question_may_name_are_listed_under_each_lesson_of_the_batch(self):
        _, user = texts()

        assert 'Allowed concepts (copy one exactly into "concept"): ["Halving the range", "Time complexity"]' in user
        assert 'Allowed concepts (copy one exactly into "concept"): ["Merge sort"]' in user
        assert user.index("SUMMARY-A") < user.index("Halving the range") < user.index("SUMMARY-B")
        assert "Merge sort" not in texts(batch={"id": "b", "cells": CELLS[:2]})[1]

    def test_a_lesson_without_concepts_and_a_topic_quiz_list_none(self):
        sources = {"a": {**QUIZ["sources"]["a"], "concepts": []}}

        assert "Allowed concepts" not in texts(quiz=QUIZ | {"sources": sources})[1]
        assert "Allowed concepts" not in texts(quiz=QUIZ | {"sources": {}})[1]

    def test_questions_already_asked_are_given_shortened_and_capped(self):
        asked = [f"Question number {n} " + "x" * 400 for n in range(100)]

        _, user = texts(exclusions=asked)

        assert "Question number 99" in user and "Question number 0 " not in user
        assert "x" * 200 not in user

    def test_a_programming_quiz_with_written_answers_may_ask_for_code(self):
        written = [{"index": 0, "type": "short_answer", "difficulty": "easy", "marks": 2, "source": ""}]

        system, _ = texts(quiz={**QUIZ, "code_format": True}, batch={"id": "b", "cells": written})

        assert "write code" in system and '"language"' in system

    def test_without_the_code_format_the_model_is_not_asked_for_code(self):
        system, _ = texts()

        assert "starter_code" not in system and "answer is code" not in system

    def test_feedback_and_the_language_rule_are_included(self):
        messages = WriteQuizQuestionsPrompt().messages(subject(profile={"preferred_language": "hi"}), ["Fix Q2."])

        assert "Hindi" in messages[0].content and "Fix Q2." in messages[1].content


class TestThePoolPrompt:
    SETTINGS = {"diagnostic_questions_per_band": 2, "prerequisite_question_count": 5}

    def system(self, **fields):
        subject = {"settings": self.SETTINGS, "profile": None, "topic": "Algorithms"} | fields
        return DiagnosticPrompt().messages(subject)[0].content

    def test_a_pool_asks_for_two_questions_per_band_and_no_prerequisite_quiz(self):
        system = self.system(include_prerequisites=False)

        assert "exactly 10 multiple-choice questions" in system
        assert "PREREQUISITE QUIZ" not in system and "empty" in system

    def test_the_normal_prompt_still_asks_for_the_prerequisite_quiz(self):
        assert "PREREQUISITE QUIZ" in self.system()
        assert "PREREQUISITE QUIZ" in self.system(include_prerequisites=True)
