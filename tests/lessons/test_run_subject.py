"""Unit under test: `lessons.subjects.RunSubject`, `GraphRun.subject` and the `GraphRun` queryset helpers
(`for_subject`, `owned_by`, `with_subject`), which let the run machinery treat "what a run belongs to" as one thing.

Why: the runner, Stop, Retry and the console reach a run's owner object through `run.subject`, so an object other
than a lesson (a quick quiz) can have runs without changing any of them. If the port drifts from `Lesson` or
`QuickQuiz`, or the queryset helpers miss a run or leak another learner's, Stop and Retry act on the wrong rows.

Use cases:
- a lesson satisfies the `RunSubject` port, and an object without its methods does not
- a run's subject is its lesson, or its quick quiz, and its id is known without a query
- a run belongs to exactly one of the two: neither, or both, is refused by the database
- a fresh subject is read from the database, so it sees what the graph changed meanwhile
- `for_subject` returns only that lesson's (or quiz's) runs, and refuses an object that cannot have runs
- `for_subject_id` finds the runs of a subject that is only known by its id, lesson or quiz
- `owned_by` returns the runs of a learner's own lessons and quizzes only
- `with_subject` fetches the subject (and optionally its owner) in the same query, for either kind
"""

import pytest
from django.db import IntegrityError, transaction

from lessons.models import GraphRun, Lesson
from lessons.stages import Stage
from lessons.subjects import RunSubject

pytestmark = pytest.mark.django_db


def make_run(lesson, **fields):
    fields.setdefault("trigger", GraphRun.Trigger.START)
    return GraphRun.objects.create(lesson=lesson, **fields)


class TestPort:
    def test_a_lesson_satisfies_the_port(self, lesson):
        assert isinstance(lesson, RunSubject)

    def test_an_object_without_the_port_s_members_does_not(self):
        class NotASubject:
            id = "1"

        assert not isinstance(NotASubject(), RunSubject)


class TestSubject:
    def test_the_subject_of_a_run_is_its_lesson(self, lesson):
        run = make_run(lesson)

        assert run.subject == lesson
        assert run.subject_id == lesson.id

    def test_the_subject_id_needs_no_query(self, lesson, django_assert_num_queries):
        run = GraphRun.objects.get(pk=make_run(lesson).pk)

        with django_assert_num_queries(0):
            assert run.subject_id == lesson.id

    def test_a_fresh_subject_is_read_from_the_database(self, lesson):
        run = GraphRun.objects.with_subject().get(pk=make_run(lesson).pk)
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.READY)

        assert run.subject.stage == Stage.PREPARING_DIAGNOSTIC  # the copy the run already holds
        assert run.fresh_subject().stage == Stage.READY


class TestQuerySet:
    def test_for_subject_returns_only_that_lessons_runs(self, make_lesson):
        mine, theirs = make_lesson(), make_lesson()
        first, second = make_run(mine), make_run(mine, trigger=GraphRun.Trigger.RETRY)
        make_run(theirs)

        assert set(GraphRun.objects.for_subject(mine)) == {first, second}

    def test_for_subject_refuses_an_object_that_cannot_have_runs(self):
        with pytest.raises(TypeError):
            GraphRun.objects.for_subject(object())

    def test_owned_by_returns_the_runs_of_the_learners_own_lessons(self, make_lesson, user, other_user):
        mine = make_run(make_lesson(owner=user))
        make_run(make_lesson(owner=other_user))

        assert list(GraphRun.objects.owned_by(user)) == [mine]

    def test_with_subject_fetches_the_lesson_in_the_same_query(self, lesson, django_assert_num_queries):
        run_id = make_run(lesson).pk

        with django_assert_num_queries(1):
            run = GraphRun.objects.with_subject().get(pk=run_id)
            assert run.subject.topic == "Binary search"

    def test_with_subject_can_fetch_the_owner_too(self, lesson, user, django_assert_num_queries):
        run_id = make_run(lesson).pk

        with django_assert_num_queries(1):
            run = GraphRun.objects.with_subject(owner=True).get(pk=run_id)
            assert run.subject.owner.email == user.email


class TestQuizRuns:
    """A run of a quick quiz: the same machinery, the other column."""

    def quiz_run(self, quiz, **fields):
        fields.setdefault("trigger", GraphRun.Trigger.START)
        return GraphRun.objects.create(quick_quiz=quiz, graph=GraphRun.Graph.QUICK_QUIZ, **fields)

    def test_the_subject_of_a_quiz_run_is_its_quiz(self, quiz):
        run = self.quiz_run(quiz)

        assert run.subject == quiz and run.subject_id == quiz.id and run.lesson_id is None

    def test_a_fresh_quiz_subject_sees_what_the_graph_changed(self, quiz):
        run = GraphRun.objects.with_subject().get(pk=self.quiz_run(quiz).pk)
        type(quiz).objects.filter(pk=quiz.pk).update(error="changed")

        assert run.subject.error == "" and run.fresh_subject().error == "changed"

    def test_the_subject_id_of_a_quiz_run_needs_no_query(self, quiz, django_assert_num_queries):
        run = GraphRun.objects.get(pk=self.quiz_run(quiz).pk)

        with django_assert_num_queries(0):
            assert run.subject_id == quiz.id

    def test_a_run_with_neither_subject_is_refused(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            GraphRun.objects.create(trigger=GraphRun.Trigger.START)

    def test_a_run_with_both_subjects_is_refused(self, lesson, quiz):
        with pytest.raises(IntegrityError), transaction.atomic():
            GraphRun.objects.create(lesson=lesson, quick_quiz=quiz, trigger=GraphRun.Trigger.START)

    def test_for_subject_returns_the_runs_of_that_quiz_only(self, quiz, make_quiz, lesson):
        mine = self.quiz_run(quiz)
        self.quiz_run(make_quiz(topic="Sorting"))
        make_run(lesson)

        assert list(GraphRun.objects.for_subject(quiz)) == [mine]

    def test_for_subject_id_finds_a_lessons_runs_and_a_quizs_alike(self, lesson, quiz):
        lesson_run, quiz_run = make_run(lesson), self.quiz_run(quiz)

        assert list(GraphRun.objects.for_subject_id(lesson.id)) == [lesson_run]
        assert list(GraphRun.objects.for_subject_id(quiz.id)) == [quiz_run]

    def test_owned_by_covers_a_learners_quizzes_and_lessons_and_no_one_elses(
        self, lesson, quiz, make_quiz, make_lesson, user, other_user
    ):
        mine = {make_run(lesson), self.quiz_run(quiz)}
        make_run(make_lesson(owner=other_user))
        self.quiz_run(make_quiz(owner=other_user, topic="Theirs"))

        assert set(GraphRun.objects.owned_by(user)) == mine

    def test_with_subject_fetches_either_kind_in_one_query(self, lesson, quiz, user, django_assert_num_queries):
        ids = [make_run(lesson).pk, self.quiz_run(quiz).pk]

        with django_assert_num_queries(1):
            runs = list(GraphRun.objects.with_subject(owner=True).filter(pk__in=ids))
            assert {run.subject.owner.email for run in runs} == {user.email}
