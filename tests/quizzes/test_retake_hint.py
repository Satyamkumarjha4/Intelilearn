"""Unit under test: the size hints `QuickQuizService.retake` gives the action gate for `quiz.retake`.

Why: a retake is priced like the quiz it repeats: a quiz made from lessons costs one credit more than a topic quiz of
the same length (credits plan K10). Before this hint the retake carried only the question count, so a price rule
could not tell the two apart. The hint is a plain fact about the quiz, so it is added now, ahead of any pricing.

Use cases:
- a retake of a topic quiz asks the gate for `quiz.retake` with the count and `source_type: topic`
- a retake of a quiz made from lessons says `source_type: lessons`
- no hint other than the count and the source type is sent
"""

import pytest
from support.gates import CountingGate

from quizzes.services import QuickQuizService

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("source_type", ["topic", "lessons"])
def test_a_retake_tells_the_gate_what_the_quiz_was_made_from(make_quiz, make_attempt, queue, source_type):
    quiz = make_quiz(source_type=source_type)
    make_attempt(quiz, status="graded", questions=[{"id": "t1"}], awarded=1, available=1)
    gate = CountingGate()

    QuickQuizService(queue=queue, gate=gate).retake(quiz)

    (asked,) = gate.authorized
    assert str(asked.action) == "quiz.retake"
    assert asked.size["source_type"] == source_type and asked.size["num_questions"] == quiz.config["num_questions"]


def test_the_hint_is_the_only_one_added_to_the_retake(make_quiz, make_attempt, queue):
    quiz = make_quiz()
    make_attempt(quiz, status="graded", questions=[{"id": "t1"}], awarded=1, available=1)
    gate = CountingGate()

    QuickQuizService(queue=queue, gate=gate).retake(quiz)

    assert set(gate.authorized[0].size) == {"num_questions", "source_type"}
