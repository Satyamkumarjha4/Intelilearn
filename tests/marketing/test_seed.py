"""Unit under test: migration `marketing.0002_seed_demo_questions`, the 25 questions the hero card starts with.

Why: these are shown to every visitor with nothing between the data and the page. A wrong "correct" answer is a bad
first impression of a tutor; a question that does not fit its card, or a bank that is all one subject or one
difficulty, makes the page feel careless. The answers are checked here against a separately written answer key
(`answer_key.py`).

Use cases:
- 25 questions are seeded, all active, each valid by the model's own rules
- the answer of every question is the one in the reviewed answer key, and nothing is seeded that the key does not know
- the spread: every subject asked for is there (Maths and computer science twice or more), levels run from Class 6 to
  college and working, and every band 1 to 5 has several questions
- every question is short (two lines on the card), every option is short, and no question or option is repeated
- the outcomes sit with the band: a right answer leaves the learner at or above a wrong one, a hard question's right
  answer is higher than an easy question's, and every outcome says where the lesson would begin
- the question the page shows when the API cannot be reached (frontend/lib/landing-content.ts) is not one of the seeded
  ones, or a visitor whose request failed would see the same question twice
- seeding twice does not duplicate, and undoing the migration removes only the seeded questions
"""

from importlib import import_module

import pytest
from django.apps import apps as django_apps
from support.answer_key import ANSWER_KEY

from marketing.models import DemoQuestion

pytestmark = pytest.mark.django_db

SUBJECTS_ASKED_FOR = {
    "Physics", "Chemistry", "Biology", "Maths", "Computer science", "Economics", "Personal finance", "History",
    "Geography", "English grammar", "Environmental science", "Statistics", "General science",
}  # fmt: skip


@pytest.fixture
def questions():
    return list(DemoQuestion.objects.order_by("id"))


def test_twenty_five_valid_active_questions_are_seeded(questions):
    assert len(questions) == 25
    assert all(q.is_active for q in questions)
    for question in questions:
        question.full_clean()


def test_every_answer_is_the_one_in_the_reviewed_key(questions):
    assert {q.question for q in questions} == set(ANSWER_KEY)
    for question in questions:
        assert question.options[question.correct_index] == ANSWER_KEY[question.question], question.question


def test_the_spread_of_subjects_levels_and_bands(questions):
    subjects = [q.subject for q in questions]
    levels = {q.level_label for q in questions}
    bands = [q.band for q in questions]

    assert set(subjects) == SUBJECTS_ASKED_FOR
    assert subjects.count("Maths") >= 2 and subjects.count("Computer science") >= 2
    assert {"Class 6", "Class 10", "Class 12", "College", "Working"} <= levels
    assert all(bands.count(band) >= 3 for band in range(1, 6))
    assert max(bands.count(band) for band in range(1, 6)) <= 7


def test_questions_and_options_are_short_and_not_repeated(questions):
    texts = [q.question for q in questions]
    assert max(len(t) for t in texts) <= 85  # two lines at 21px in the hero card
    assert len(set(texts)) == len(texts)
    for question in questions:
        assert max(len(option) for option in question.options) <= 60, question.question


def test_outcomes_sit_with_the_band(questions):
    for question in questions:
        right, wrong = question.outcome_right, question.outcome_wrong
        assert right["level"] >= wrong["level"], question.question
        assert right["lesson_start"] != wrong["lesson_start"]
    easy = [q.outcome_right["level"] for q in questions if q.band == 1]
    hard = [q.outcome_right["level"] for q in questions if q.band == 5]
    assert max(easy) < min(hard)
    labels = {}
    for question in questions:
        for outcome in (question.outcome_right, question.outcome_wrong):
            labels.setdefault(outcome["level"], set()).add(outcome["level_label"])
    assert all(len(names) == 1 for names in labels.values())  # one name per level, so the meter always reads the same


def test_seeding_twice_does_not_duplicate_and_undoing_removes_only_the_seeded():
    migration = import_module("marketing.migrations.0002_seed_demo_questions")
    DemoQuestion.objects.create(
        subject="Art",
        level_label="Class 7",
        band=1,
        question="Mine?",
        options=["a", "b", "c"],
        correct_index=0,
        outcome_right={"level": 2, "level_label": "Building up", "lesson_start": "x"},
        outcome_wrong={"level": 1, "level_label": "New to it", "lesson_start": "y"},
    )

    migration.seed(django_apps, None)
    assert DemoQuestion.objects.count() == 26

    migration.unseed(django_apps, None)
    assert list(DemoQuestion.objects.values_list("question", flat=True)) == ["Mine?"]


# Mirrors HERO_FALLBACK_QUESTION in frontend/lib/landing-content.ts (the two containers cannot read each other's files).
FRONTEND_FALLBACK = {"question": "Which is larger: 3/4 or 2/3?", "options": ["3/4", "2/3", "They are equal"]}


def test_the_question_shown_when_the_api_is_down_is_not_one_of_the_seeded_ones(questions):
    assert FRONTEND_FALLBACK["question"] not in {q.question for q in questions}
    seeded_options = {option for q in questions for option in q.options}
    assert not seeded_options & set(FRONTEND_FALLBACK["options"])
