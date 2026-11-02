"""Putting the questions a lesson was built with on its record, for tests (`Lesson.final_test` is gone)."""

from lessons.bank import QuestionBank


def seed_first_set(lesson, questions: list[dict]) -> list[dict]:
    """Puts `questions` on the lesson's record as the set it was built with (attempt 1). → the stored copies."""
    bank = QuestionBank()
    stored = bank.add(lesson.id, None, [{k: v for k, v in q.items() if k != "question_id"} for q in questions])
    bank.set_first_set(lesson.id, stored)
    return stored
