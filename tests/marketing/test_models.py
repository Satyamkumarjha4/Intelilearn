"""Unit under test: `marketing.models.DemoQuestion`, one question of the landing page's try-it bank.

Why: a row is typed into the Django admin by a person and shown, unchecked, to every visitor of the front page. A
question with two options, a correct answer that points at nothing, or an outcome without text would break the card in
front of the very people the page is trying to win, so the model refuses all of them when it is saved from the admin.

Use cases:
- a complete question is valid, is active by default, and prints as its question
- the options are exactly three non-empty, different texts
- the correct answer is the index of one of the options
- the band is 1 to 5
- each outcome has a level from 1 to 5, a level label and a lesson start; the right answer never leaves a learner at a
  lower level than the wrong one
- subject, level label and question must not be blank
"""

import pytest
from django.core.exceptions import ValidationError

from marketing.models import DemoQuestion

pytestmark = pytest.mark.django_db


def make(**fields):
    values = dict(
        subject="Physics",
        level_label="Class 9",
        band=3,
        question="A ball is thrown straight up. At the very top of its flight, its speed is…",
        options=["Zero", "At its fastest", "The same as when it was thrown"],
        correct_index=0,
        outcome_right={"level": 3, "level_label": "Getting there", "lesson_start": "Why the ball slows down."},
        outcome_wrong={"level": 2, "level_label": "Building up", "lesson_start": "What speed and velocity mean."},
    )
    return DemoQuestion(**{**values, **fields})


def test_a_complete_question_is_valid_active_and_prints_as_its_question():
    question = make()
    question.full_clean()
    question.save()

    assert question.is_active is True and question.created_at is not None
    assert str(question) == question.question


@pytest.mark.parametrize(
    "options",
    [
        ["Zero", "At its fastest"],
        ["Zero", "At its fastest", "Slow", "Fast"],
        ["Zero", "", "Slow"],
        ["Zero", "  ", "Slow"],
        ["Zero", "Zero", "Slow"],
        ["Zero", "zero ", "Slow"],
        ["Zero", 2, "Slow"],
        "Zero",
        None,
    ],
)
def test_the_options_are_exactly_three_different_texts(options):
    with pytest.raises(ValidationError) as raised:
        make(options=options).full_clean()
    assert "options" in raised.value.message_dict


@pytest.mark.parametrize("index", [-1, 3, 7])
def test_the_correct_answer_is_one_of_the_options(index):
    with pytest.raises(ValidationError) as raised:
        make(correct_index=index).full_clean()
    assert "correct_index" in raised.value.message_dict


@pytest.mark.parametrize("band", [0, 6])
def test_the_band_is_one_to_five(band):
    with pytest.raises(ValidationError) as raised:
        make(band=band).full_clean()
    assert "band" in raised.value.message_dict


@pytest.mark.parametrize(
    "bad",
    [
        {"level": 0, "level_label": "x", "lesson_start": "y"},
        {"level": 6, "level_label": "x", "lesson_start": "y"},
        {"level": "3", "level_label": "x", "lesson_start": "y"},
        {"level": 3, "level_label": "", "lesson_start": "y"},
        {"level": 3, "level_label": "x", "lesson_start": " "},
        {"level": 3, "level_label": "x"},
        {"level": 3, "level_label": "x", "lesson_start": "y", "extra": 1},
        [],
        None,
    ],
)
@pytest.mark.parametrize("field", ["outcome_right", "outcome_wrong"])
def test_each_outcome_has_a_level_a_label_and_a_lesson_start(field, bad):
    with pytest.raises(ValidationError) as raised:
        make(**{field: bad}).full_clean()
    assert field in raised.value.message_dict


def test_the_right_answer_never_leaves_a_learner_lower_than_the_wrong_one():
    question = make(
        outcome_right={"level": 2, "level_label": "Building up", "lesson_start": "a"},
        outcome_wrong={"level": 3, "level_label": "Getting there", "lesson_start": "b"},
    )

    with pytest.raises(ValidationError) as raised:
        question.full_clean()
    assert "outcome_right" in raised.value.message_dict


@pytest.mark.parametrize("field", ["subject", "level_label", "question"])
def test_subject_level_label_and_question_must_not_be_blank(field):
    with pytest.raises(ValidationError) as raised:
        make(**{field: "  "}).full_clean()
    assert field in raised.value.message_dict
