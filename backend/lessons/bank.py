"""The record of the questions a lesson has asked (`Question`), and what a retake needs from it.

`QuestionBank` is the only writer of those rows. A question is immutable once it is written: a retake only adds rows,
and a question is withdrawn (retired), never edited or deleted, so every attempt that was served it stays valid.
"""

import uuid

from django.db import transaction

from graph.questions import StemHash

from .models import Lesson, Question, TestSubmission


class QuestionBank:
    def add(self, lesson_id, batch_id: uuid.UUID | None, questions: list[dict]) -> list[dict]:
        """Write the questions to the record → copies, each with `question_id` (the row's id). A stem the lesson has
        asked already keeps its row, and that row's id is returned, so one question has one row."""
        stored = []
        for question in questions:
            row, _ = Question.objects.get_or_create(
                lesson_id=lesson_id,
                stem_hash=StemHash.of(question["question"]),
                defaults={
                    "type": question["type"],
                    "difficulty": question["difficulty"],
                    "concept": str(question.get("concept", ""))[:200],
                    "marks": question["marks"],
                    "payload": question,
                    "batch": batch_id,
                },
            )
            stored.append({**question, "question_id": str(row.id)})
        return stored

    def set_first_set(self, lesson_id, stored: list[dict]) -> None:
        """The questions a lesson was built with, in order: what attempt 1 will serve. `stored` are the copies `add`
        returned. Writing a set again replaces the old one (a build that is run again)."""
        with transaction.atomic():
            Question.objects.filter(lesson_id=lesson_id).update(first_set_position=None)
            for position, question in enumerate(stored):
                Question.objects.filter(lesson_id=lesson_id, pk=question["question_id"]).update(
                    first_set_position=position
                )

    def replace_in_first_set(self, lesson_id, old_question_id, stored: dict) -> None:
        """One question of the set written again (a fix after the review): the new one stands where the old one did and
        the old row is retired."""
        with transaction.atomic():
            old = Question.objects.select_for_update().filter(lesson_id=lesson_id, pk=old_question_id).first()
            if old is None or old.first_set_position is None:
                raise LookupError(f"Question {old_question_id} is not in the lesson's first set.")
            position = old.first_set_position
            Question.objects.filter(pk=old.pk).update(first_set_position=None, retired=True)
            Question.objects.filter(lesson_id=lesson_id, pk=stored["question_id"]).update(first_set_position=position)

    def first_set(self, lesson: Lesson) -> list[dict]:
        """The questions the lesson was built with, in order, as attempt 1 serves them: the whole question with its
        answer key and the id of its row. Empty for a lesson without one."""
        rows = Question.objects.filter(lesson=lesson, first_set_position__isnull=False).order_by("first_set_position")
        return [{**row.payload, "question_id": str(row.id)} for row in rows]

    def retire(self, lesson_id, question_id) -> None:
        Question.objects.filter(lesson_id=lesson_id, pk=question_id).update(retired=True)

    def exclusions(self, lesson: Lesson) -> list[str]:
        """The text of every question the lesson has asked, oldest first, each once: the record (retired rows too, so
        an old stem never comes back), the lesson's own test and every attempt's snapshot."""
        stems = [row["payload"]["question"] for row in Question.objects.filter(lesson=lesson).values("payload")]
        stems += [q["question"] for q in self._served(lesson)]
        return list(dict.fromkeys(stems))

    def leftovers(self, lesson: Lesson) -> list[dict]:
        """Written but never served: not retired, and in neither the lesson's first set nor an attempt. Each is
        `{id, type, difficulty, retired, question}` where `question` is the full stored question."""
        served = {q.get("question_id") for q in self._served(lesson)}
        rows = Question.objects.filter(lesson=lesson, retired=False)
        return [
            {"id": str(r.id), "type": r.type, "difficulty": r.difficulty, "retired": r.retired, "question": r.payload}
            for r in rows
            if str(r.id) not in served
        ]

    @staticmethod
    def _served(lesson: Lesson) -> list[dict]:
        """Every question the lesson's first set and its attempts have shown."""
        served = QuestionBank().first_set(lesson)
        for snapshot in TestSubmission.objects.filter(lesson=lesson).values_list("questions", flat=True):
            served += snapshot or []
        return served
