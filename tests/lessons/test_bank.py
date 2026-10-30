"""Unit under test: `lessons.bank.QuestionBank`, the only writer of the `Question` rows and the source of a retake's
exclusion list and of the unserved questions left over.

Why: the record is what keeps a retake from repeating a question, so it must be complete (every question ever asked,
old tests and attempts included), immutable (a question is never edited, only retired) and cheap to ask about. A
question must have exactly one row however many times the same stem is added, because the row id is how a snapshot
points back at it.

Use cases:
- adding questions writes a row each, gives every question its row id, and does not change the questions it was given
- adding the same stem again does not make a second row and returns the row that is there
- the marks, type, difficulty, concept and batch of the row come from the question and the run
- retiring a question keeps its row but marks it withdrawn
- the exclusion list holds every stem the lesson has asked: the record (retired too), the lesson's own test and the
  questions of every attempt, each once, oldest first
- the leftovers are the unretired rows that no test or attempt has served
"""

import uuid

import pytest
from support.lesson_data import make_blueprint_test

from lessons.bank import QuestionBank
from lessons.models import Question, TestSubmission

pytestmark = pytest.mark.django_db

BATCH = uuid.UUID("11111111-1111-1111-1111-111111111111")


def test_adding_questions_writes_a_row_each_and_gives_every_question_its_row_id(lesson):
    questions = make_blueprint_test()["questions"][:3]
    before = [dict(q) for q in questions]

    stored = QuestionBank().add(lesson.id, BATCH, questions)

    assert questions == before  # the input is not changed
    rows = {str(r.id): r for r in Question.objects.filter(lesson=lesson)}
    assert [q["question_id"] for q in stored] and set(q["question_id"] for q in stored) == set(rows)
    first = rows[stored[0]["question_id"]]
    assert (first.type, first.difficulty, first.marks, first.batch) == ("mcq", "easy", 1, BATCH)
    assert first.concept == questions[0]["concept"] and first.payload == questions[0] and first.retired is False
    assert len(first.stem_hash) == 64


def test_adding_the_same_stem_again_makes_no_second_row_and_returns_the_row_that_is_there(lesson):
    question = make_blueprint_test()["questions"][0]
    (first,) = QuestionBank().add(lesson.id, BATCH, [question])

    (again,) = QuestionBank().add(
        lesson.id, uuid.uuid4(), [{**question, "id": "t9", "question": question["question"].upper()}]
    )

    assert again["question_id"] == first["question_id"] and Question.objects.filter(lesson=lesson).count() == 1


def test_retiring_a_question_keeps_its_row_and_marks_it_withdrawn(lesson):
    (stored,) = QuestionBank().add(lesson.id, BATCH, make_blueprint_test()["questions"][:1])

    QuestionBank().retire(lesson.id, stored["question_id"])

    row = Question.objects.get(pk=stored["question_id"])
    assert row.retired is True and row.payload["question"] == stored["question"]


def test_retiring_a_question_of_another_lesson_changes_nothing(lesson, make_lesson):
    (stored,) = QuestionBank().add(lesson.id, BATCH, make_blueprint_test()["questions"][:1])

    QuestionBank().retire(make_lesson().id, stored["question_id"])

    assert Question.objects.get(pk=stored["question_id"]).retired is False


class TestExclusions:
    def test_a_lesson_that_has_asked_nothing_has_nothing_to_exclude(self, lesson):
        assert QuestionBank().exclusions(lesson) == []

    def test_every_stem_the_lesson_has_asked_is_listed_once_oldest_first(self, lesson):
        test = make_blueprint_test()
        lesson.record(final_test={"title": "T", "questions": test["questions"][:3]})
        QuestionBank().add(lesson.id, BATCH, test["questions"][:2])  # on the record and in the test: once
        (retired,) = QuestionBank().add(lesson.id, BATCH, test["questions"][3:4])
        QuestionBank().retire(lesson.id, retired["question_id"])
        TestSubmission.objects.create(lesson=lesson, status="graded", questions=test["questions"][4:6])

        stems = QuestionBank().exclusions(lesson)

        assert sorted(stems) == sorted(q["question"] for q in test["questions"][:6])
        assert len(stems) == 6

    def test_the_questions_of_another_lesson_are_not_listed(self, lesson, make_lesson):
        QuestionBank().add(make_lesson().id, BATCH, make_blueprint_test()["questions"][:2])

        assert QuestionBank().exclusions(lesson) == []


class TestLeftovers:
    def test_a_written_question_nobody_was_served_is_a_leftover(self, lesson):
        stored = QuestionBank().add(lesson.id, BATCH, make_blueprint_test()["questions"][:3])

        left = QuestionBank().leftovers(lesson)

        assert sorted(q["id"] for q in left) == sorted(q["question_id"] for q in stored)
        assert {"type", "difficulty", "retired", "question"} <= set(left[0])

    def test_questions_in_the_lessons_test_or_an_attempt_are_not_leftovers(self, lesson):
        test = make_blueprint_test()["questions"]
        stored = QuestionBank().add(lesson.id, BATCH, test[:4])
        lesson.record(final_test={"title": "T", "questions": stored[:1]})
        TestSubmission.objects.create(lesson=lesson, status="graded", questions=stored[1:2])

        left = QuestionBank().leftovers(lesson)

        assert sorted(q["id"] for q in left) == sorted(q["question_id"] for q in stored[2:])

    def test_a_retired_question_is_not_a_leftover(self, lesson):
        (stored,) = QuestionBank().add(lesson.id, BATCH, make_blueprint_test()["questions"][:1])
        QuestionBank().retire(lesson.id, stored["question_id"])

        assert QuestionBank().leftovers(lesson) == []
