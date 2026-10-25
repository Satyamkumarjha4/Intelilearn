"""Unit under test: `marketing.picker.DemoQuestionPicker`, which chooses the question the hero card shows next.

Why: every load of the landing page asks for one, so it has to be cheap (the list of candidates is cached, not read
from the database each time), fair (random, and never the question the visitor has just seen), and safe (an empty
table, a question switched off or deleted since the list was cached, must give "none" or another question, never an
error).

Use cases:
- it picks among the active questions only, and every one of them can come up
- it never picks the one asked to be excluded, unless that is the only question there is
- the list of active ids is read once and then served from the cache for ten minutes
- saving or deleting a question (the admin) clears that list at once
- an id that was cached but has been deleted or switched off since is skipped for a fresh list, not an error
- with no active question it picks nothing
- the options of the question it hands back are shuffled, so the right answer is not always in the same place: the same
  three texts, the right one still the right one at its new position, every position possible, and the stored row is
  never changed
"""

import random

import pytest
from django.core.cache import cache

from marketing.models import DemoQuestion
from marketing.picker import DemoQuestionPicker

pytestmark = pytest.mark.django_db

RIGHT = {"level": 3, "level_label": "Getting there", "lesson_start": "a"}
WRONG = {"level": 2, "level_label": "Building up", "lesson_start": "b"}


@pytest.fixture
def make():
    def _make(text, **fields):
        return DemoQuestion.objects.create(
            **{
                "subject": "Maths",
                "level_label": "Class 6",
                "band": 1,
                "question": text,
                "options": ["a", "b", "c"],
                "correct_index": 0,
                "outcome_right": RIGHT,
                "outcome_wrong": WRONG,
            }
            | fields
        )

    return _make


@pytest.fixture(autouse=True)
def empty_bank():
    DemoQuestion.objects.all().delete()  # the seed migration's questions are not what these tests are about
    cache.clear()


def test_it_picks_among_the_active_questions_and_every_one_can_come_up(make):
    a, b, c = make("A"), make("B"), make("C")
    make("off", is_active=False)
    picker = DemoQuestionPicker(rng=random.Random(1))

    seen = {picker.pick().pk for _ in range(60)}

    assert seen == {a.pk, b.pk, c.pk}


def test_it_never_picks_the_excluded_one_unless_it_is_the_only_one(make):
    a, b = make("A"), make("B")
    picker = DemoQuestionPicker(rng=random.Random(2))

    assert {picker.pick(exclude=a.pk).pk for _ in range(30)} == {b.pk}
    b.is_active = False
    b.save()
    assert picker.pick(exclude=a.pk).pk == a.pk


def test_the_list_of_ids_is_read_once_then_served_from_the_cache(make, django_assert_num_queries):
    make("A")
    make("B")
    picker = DemoQuestionPicker()
    picker.pick()  # fills the cache: one query for the ids, one for the row

    with django_assert_num_queries(1):  # only the chosen row
        picker.pick()


def test_the_ids_stay_cached_for_ten_minutes(make):
    from support.fakes import RecordingCache

    make("A")
    cache_double = RecordingCache()

    DemoQuestionPicker(cache=cache_double).pick()

    assert set(cache_double.timeouts.values()) == {600}


def test_saving_or_deleting_a_question_clears_the_list_at_once(make):
    a = make("A")
    picker = DemoQuestionPicker(rng=random.Random(3))
    picker.pick()
    b = make("B")  # a new question is part of the next list, without waiting ten minutes

    assert {picker.pick().pk for _ in range(40)} == {a.pk, b.pk}
    a.delete()
    assert {picker.pick().pk for _ in range(10)} == {b.pk}


def test_an_id_cached_but_gone_since_is_skipped_for_a_fresh_list(make):
    a, b = make("A"), make("B")
    picker = DemoQuestionPicker(rng=random.Random(4))
    picker.pick()
    # Gone behind the cache's back: a queryset delete sends no signal, as a database clean-up would not either.
    DemoQuestion.objects.filter(pk=a.pk).delete()

    assert {picker.pick().pk for _ in range(20)} == {b.pk}


def test_with_no_active_question_it_picks_nothing(make):
    assert DemoQuestionPicker().pick() is None
    make("off", is_active=False)
    assert DemoQuestionPicker().pick() is None


def test_the_options_are_shuffled_and_the_right_one_goes_with_its_text(make):
    stored = make("A", options=["right", "wrong 1", "wrong 2"])  # stored with the right answer first
    picker = DemoQuestionPicker(rng=random.Random(5))

    drawn = [picker.pick() for _ in range(60)]

    for question in drawn:
        assert sorted(question.options) == ["right", "wrong 1", "wrong 2"]
        assert question.options[question.correct_index] == "right"
    assert {question.correct_index for question in drawn} == {0, 1, 2}  # every position comes up
    stored.refresh_from_db()
    assert (
        stored.options == ["right", "wrong 1", "wrong 2"] and stored.correct_index == 0
    )  # the row itself is untouched


def test_shuffling_keeps_everything_but_the_options_and_their_order(make):
    stored = make("A")

    question = DemoQuestionPicker(rng=random.Random(6)).pick()

    assert (question.pk, question.question, question.outcome_right, question.outcome_wrong) == (
        stored.pk, "A", RIGHT, WRONG
    )  # fmt: skip
