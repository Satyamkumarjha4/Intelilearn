"""Unit under test: `quizzes.services.QuickQuizService` (make, retake, delete, a lesson from a result) and
`CalibrationService` (the five-question walk).

Why: this is where a quiz is decided. Every rule of the request is enforced here whatever the screen hides, the action
gate is asked once and before anything exists, a retake never repeats a question or draws two sets, a delete leaves
nothing of the learner's behind, and the calibration walk is the server's: the learner sees one question with no tier
and answers it once, and the ladder, not the browser, decides the next.

Use cases:
- a topic quiz is made with its settings, hash, registry snapshot and judged traits, a waiting first attempt and a
  queued start run, and the gate was asked for `quiz.create` once with the sizes
- a quiz from lessons records each lesson's level and share (even split, the remainder to the most recent), their
  scores set the levels when asked, and a rating or calibration overrides them
- every rule of the request is refused before anything is asked or created: the count, the kinds, the limits, a lesson
  that is sheets only or not ready, someone else's lesson, scores with no graded test, a model that is not bound
- a topic nobody could judge allows every kind its count allows; a judged non-quantitative topic refuses numerical
- the same settings give the same hash; a gate that refuses creates nothing; the idempotency key reaches the gate
- a retake is a new attempt with a queued run and one `quiz.retake`; an open attempt is returned with no new ask; it
  needs a ready quiz and live source lessons, and is limited per day
- delete stops the runs, settles the authorization cancelled, erases the checkpoints and model calls, and removes the
  quiz
- the calibration walk: one question at a time with no band or answer, final, in the ladder's order; after the last
  answer one resume run carries the authorization on; a stale or repeated answer is refused
- a lesson is made from a topic quiz's graded attempt, with the origin and level from the result; a quiz from lessons,
  an attempt that is not graded or not the quiz's are refused
"""

import pytest
from rest_framework.exceptions import NotFound, ValidationError
from support.gates import CountingGate, RefusingGate

from graph.questions.traits import TopicTraits
from lessons.errors import LessonNotConfigured, RetakeLimitReached, WrongStage
from lessons.metering import ActionRefused
from lessons.models import FlowSettings, GraphRun, Lesson, TestSubmission
from llm_registry.models import ModelCall
from quizzes.errors import SourceMissing, SourceNotUsable
from quizzes.models import QuickQuiz, QuickQuizAttempt, QuickQuizSource
from quizzes.services import QuickQuizService

pytestmark = pytest.mark.django_db

RATING = {"mode": "self_rating", "rating": 3}
CALIBRATION = {"mode": "calibration"}
TOPIC = {"type": "topic", "topic": "Binary search"}


@pytest.fixture
def make(queue, bound_registry, traits_for):
    """A service with a recording queue, a bound registry, a counting gate and a judge that says maths."""

    def _make(gate=None, traits=None):
        gate = gate or CountingGate()
        service = QuickQuizService(queue=queue, gate=gate, traits=traits or traits_for())
        service.gate = gate
        return service

    return _make


def create(service, user, **overrides):
    request = {"source": TOPIC, "num_questions": 10, "types": ["mcq"], "level": RATING} | overrides
    return service.create(user, **request)


def graded(lesson, awarded, available=20, band="", number=1):
    return TestSubmission.objects.create(
        lesson=lesson, attempt_no=number, status="graded", awarded=awarded, available=available, band=band,
        result={"score": {"awarded": awarded, "available": available}}, answers={},
    )  # fmt: skip


class TestMakingATopicQuiz:
    def test_the_quiz_has_its_settings_snapshot_hash_and_traits(self, make, user):
        service = make()

        made = create(service, user, types=["mcq", "numerical"])

        quiz = QuickQuiz.objects.get(pk=made.quiz.pk)
        assert (quiz.owner, quiz.source_type, quiz.topic, quiz.stage) == (user, "topic", "Binary search", "preparing")
        assert quiz.config["num_questions"] == 10 and quiz.config["types"] == ["mcq", "numerical"]
        assert quiz.config["level_mode"] == "self_rating" and quiz.config["self_rating_halves"] == 6
        assert quiz.config["traits"] == {"quantitative": True, "programming": False}
        assert len(quiz.config_hash) == 64 and quiz.config_snapshot["nodes"]
        assert quiz.settings_snapshot == FlowSettings.load().snapshot()

    def test_the_first_attempt_waits_and_the_start_run_is_queued(self, make, user, queue):
        made = create(make(), user)

        attempt = QuickQuizAttempt.objects.get(pk=made.attempt.pk)
        assert (attempt.attempt_no, attempt.status, attempt.questions) == (1, "generating", [])
        run = GraphRun.objects.get(pk=made.run.pk)
        assert (run.graph, run.trigger, run.quick_quiz_id) == ("quick_quiz", "start", made.quiz.pk)
        assert run.payload["input"] == {"attempt_id": str(attempt.pk)}
        assert queue.runs == [made.run]

    def test_the_gate_is_asked_once_with_the_sizes(self, make, user):
        service = make()

        made = create(service, user, num_questions=15, types=["mcq", "short_answer"], level=CALIBRATION)

        (asked,) = service.gate.authorized
        assert str(asked.action) == "quiz.create" and asked.subject_id == made.quiz.pk
        assert asked.size == {
            "num_questions": 15, "source_type": "topic", "sources": 0, "level_mode": "calibration",
            "has_subjective": True,
        }  # fmt: skip
        assert asked.completes_at.kind == "run_end"
        assert made.run.payload["authorization"]["action"] == "quiz.create"

    def test_a_gate_that_refuses_creates_nothing(self, make, user, queue):
        gate = RefusingGate()

        with pytest.raises(ActionRefused):
            create(make(gate), user)

        assert QuickQuiz.objects.count() == 0 and QuickQuizAttempt.objects.count() == 0 and queue.runs == []

    def test_the_idempotency_key_reaches_the_gate(self, make, user):
        service = make()

        create(service, user, idempotency_key="abc")

        assert service.gate.authorized[0].key.endswith(":abc")

    def test_the_same_settings_give_the_same_hash_however_the_topic_is_spelled(self, make, user):
        one = create(make(), user, source={"type": "topic", "topic": "Binary search"})
        other = create(make(), user, source={"type": "topic", "topic": "  binary   SEARCH "})

        assert one.quiz.config_hash == other.quiz.config_hash and other.quiz.topic == "binary SEARCH"

    def test_other_settings_give_another_hash(self, make, user):
        one, other = create(make(), user), create(make(), user, num_questions=15)

        assert one.quiz.config_hash != other.quiz.config_hash


class TestTheRulesOfTheRequest:
    @pytest.mark.parametrize(
        ("overrides", "field"),
        [
            ({"num_questions": 12}, "num_questions"),
            ({"num_questions": 5, "types": ["mcq", "short_answer"]}, "types"),
            ({"num_questions": 5, "types": ["long_answer"]}, "types"),
            ({"types": ["essay"]}, "types"),
            ({"types": []}, "types"),
            ({"level": {"mode": "existing_score"}}, "level"),
            ({"level": {"mode": "self_rating"}}, "level"),
            ({"level": {"mode": "self_rating", "rating": 7}}, "level"),
        ],
    )
    def test_a_bad_request_is_a_400_naming_the_field_that_creates_nothing(self, make, user, queue, overrides, field):
        gate = CountingGate()

        with pytest.raises(ValidationError) as caught:
            create(make(gate), user, **overrides)

        assert field in caught.value.detail
        assert gate.authorized == [] and QuickQuiz.objects.count() == 0 and queue.runs == []

    def test_a_judged_topic_that_is_not_quantitative_refuses_numerical_questions(self, make, user, traits_for):
        service = make(traits=traits_for(TopicTraits(False, False)))

        with pytest.raises(ValidationError) as caught:
            create(service, user, types=["numerical"])

        assert "types" in caught.value.detail

    def test_a_topic_nobody_could_judge_allows_every_kind_the_count_allows(self, make, user, traits_for):
        service = make(traits=traits_for(None))

        made = create(service, user, types=["numerical", "short_answer"])

        assert made.quiz.config["types"] == ["numerical", "short_answer"] and made.quiz.config["traits"] is None

    def test_a_model_that_is_not_bound_is_a_503_before_anything_is_created(self, queue, user, traits_for, db):
        from llm_registry.node_configs import NodeConfigSync

        NodeConfigSync().ensure()

        with pytest.raises(LessonNotConfigured, match="test.generate"):
            create(QuickQuizService(queue=queue, gate=CountingGate(), traits=traits_for()), user)

        assert QuickQuiz.objects.count() == 0

    def test_a_calibration_needs_the_diagnostic_writer_too(self, make, user, bound_registry):
        from llm_registry.models import NodeModelBinding

        NodeModelBinding.objects.filter(node__node_key="diagnostic.generate").delete()

        with pytest.raises(LessonNotConfigured, match="diagnostic.generate"):
            create(make(), user, level=CALIBRATION)
        assert create(make(), user).quiz.pk  # a rated quiz does not


class TestMakingAQuizFromLessons:
    def lessons(self, make_ready_lesson, count=2):
        return [
            make_ready_lesson(f"Lesson {n}", level)
            for n, level in zip(range(count), ("beginner", "expert", "foundation"), strict=False)
        ]

    def test_each_lesson_has_its_level_and_its_share_with_the_remainder_to_the_most_recent(
        self, make, user, make_ready_lesson
    ):
        a, b, c = self.lessons(make_ready_lesson, 3)

        made = create(make(), user, source={"type": "lessons", "lesson_ids": [a.pk, b.pk, c.pk]})

        rows = list(QuickQuizSource.objects.filter(quiz=made.quiz))
        assert [(r.lesson_id, r.title, r.level, r.share) for r in rows] == [
            (a.pk, "Lesson 0", "beginner", 3), (b.pk, "Lesson 1", "expert", 3), (c.pk, "Lesson 2", "foundation", 4),
        ]  # fmt: skip
        assert made.quiz.source_type == "lessons" and made.quiz.topic == "Lesson 0 + 2 more"

    def test_the_gate_is_told_how_many_lessons(self, make, user, make_ready_lesson):
        a, b = self.lessons(make_ready_lesson)
        service = make()

        create(service, user, source={"type": "lessons", "lesson_ids": [a.pk, b.pk]})

        assert (
            service.gate.authorized[0].size["sources"] == 2
            and service.gate.authorized[0].size["source_type"] == "lessons"
        )

    def test_the_scores_set_the_levels_when_asked(self, make, user, make_ready_lesson):
        a, b = self.lessons(make_ready_lesson)  # beginner and expert
        graded(a, 19, 20, "excellent")
        graded(b, 2, 20, "fail")

        made = create(
            make(), user, source={"type": "lessons", "lesson_ids": [a.pk, b.pk]}, level={"mode": "existing_score"}
        )

        assert {r.title: r.level for r in made.quiz.sources.all()} == {
            "Lesson 0": "foundation",
            "Lesson 1": "proficient",
        }

    def test_the_latest_graded_attempt_counts_and_a_missing_band_is_worked_out(self, make, user, make_ready_lesson):
        (a,) = self.lessons(make_ready_lesson, 1)
        graded(a, 20, 20, "excellent")
        graded(a, 1, 20, "", number=2)  # the latest, from before bands were stored

        made = create(make(), user, source={"type": "lessons", "lesson_ids": [a.pk]}, level={"mode": "existing_score"})

        assert made.quiz.sources.get().level == "beginner"  # a fail moves it down; it is already the lowest

    def test_a_rating_keeps_each_lessons_own_level_for_display(self, make, user, make_ready_lesson):
        a, b = self.lessons(make_ready_lesson)

        made = create(make(), user, source={"type": "lessons", "lesson_ids": [a.pk, b.pk]})

        assert {r.level for r in made.quiz.sources.all()} == {"beginner", "expert"}

    def test_scores_with_a_lesson_that_has_no_graded_test_are_refused(self, make, user, make_ready_lesson):
        (a,) = self.lessons(make_ready_lesson, 1)

        with pytest.raises(ValidationError) as caught:
            create(make(), user, source={"type": "lessons", "lesson_ids": [a.pk]}, level={"mode": "existing_score"})

        assert "level" in caught.value.detail

    def test_a_lesson_that_is_only_study_sheets_is_refused_with_its_reason(self, make, user, make_ready_lesson):
        sheets = make_ready_lesson("Sheets", intent="sheets")

        with pytest.raises(SourceNotUsable, match="study sheets only"):
            create(make(), user, source={"type": "lessons", "lesson_ids": [sheets.pk]})

    def test_a_mastery_lesson_that_chose_sheets_is_refused(self, make, user, make_ready_lesson):
        mastery = make_ready_lesson("Mastery", route="mastery")

        with pytest.raises(SourceNotUsable):
            create(make(), user, source={"type": "lessons", "lesson_ids": [mastery.pk]})

    def test_a_lesson_still_being_built_is_refused(self, make, user, make_ready_lesson):
        building = make_ready_lesson("Building")
        Lesson.objects.filter(pk=building.pk).update(stage="generating_lesson")

        with pytest.raises(SourceNotUsable, match="not ready"):
            create(make(), user, source={"type": "lessons", "lesson_ids": [building.pk]})

    def test_another_learners_lesson_is_a_404_like_one_that_does_not_exist(
        self, make, user, other_user, make_ready_lesson
    ):
        theirs = make_ready_lesson("Theirs", owner=other_user)

        with pytest.raises(NotFound):
            create(make(), user, source={"type": "lessons", "lesson_ids": [theirs.pk]})

    def test_more_lessons_than_the_limit_are_refused(self, make, user, make_ready_lesson):
        lessons = [make_ready_lesson(f"L{n}") for n in range(11)]

        with pytest.raises(ValidationError) as caught:
            create(make(), user, num_questions=30, source={"type": "lessons", "lesson_ids": [x.pk for x in lessons]})

        assert "at most 10" in str(caught.value.detail["source"])

    def test_the_limit_is_the_admin_setting(self, make, user, make_ready_lesson):
        FlowSettings.objects.update_or_create(pk=1, defaults={"quiz_max_source_lessons": 2})
        lessons = [make_ready_lesson(f"L{n}") for n in range(3)]

        with pytest.raises(ValidationError) as caught:
            create(make(), user, source={"type": "lessons", "lesson_ids": [x.pk for x in lessons]})

        assert "at most 2" in str(caught.value.detail["source"])

    def test_a_count_below_the_number_of_lessons_is_refused(self, make, user, make_ready_lesson):
        lessons = [make_ready_lesson(f"L{n}") for n in range(6)]

        with pytest.raises(ValidationError) as caught:
            create(make(), user, num_questions=5, source={"type": "lessons", "lesson_ids": [x.pk for x in lessons]})

        assert "num_questions" in caught.value.detail

    def test_the_same_lesson_twice_is_refused(self, make, user, make_ready_lesson):
        a = make_ready_lesson("A")

        with pytest.raises(ValidationError):
            create(make(), user, source={"type": "lessons", "lesson_ids": [a.pk, a.pk]})

    def test_traits_come_from_the_lessons_plans_with_no_model_call(self, make, user, make_ready_lesson, traits_for):
        traits = traits_for()
        a = make_ready_lesson("A")
        Lesson.objects.filter(pk=a.pk).update(plan={**a.plan, "quantitative": False})

        with pytest.raises(ValidationError):
            create(make(traits=traits), user, types=["numerical"], source={"type": "lessons", "lesson_ids": [a.pk]})

        assert traits.judge.asked == []


@pytest.fixture
def ready(make, user):
    """A ready topic quiz with a graded first attempt, and the service that made it."""
    service = make()
    made = create(service, user)
    QuickQuiz.objects.filter(pk=made.quiz.pk).update(
        stage="ready", assessment={"level": "foundation", "level_scheme": 2}
    )
    QuickQuizAttempt.objects.filter(pk=made.attempt.pk).update(
        status="graded", questions=[{"id": "t1", "question": "First?"}], awarded=1, available=1
    )
    GraphRun.objects.filter(pk=made.run.pk).update(status="succeeded")
    service.gate.authorized.clear()
    return service, QuickQuiz.objects.get(pk=made.quiz.pk)


class TestRetaking:
    def test_a_retake_is_a_new_attempt_with_a_queued_run_and_one_ask(self, ready, queue):
        service, quiz = ready

        taken = service.retake(quiz)

        assert taken.created and (taken.attempt.attempt_no, taken.attempt.status) == (2, "generating")
        assert (taken.run.graph, taken.run.trigger) == ("quick_quiz", "retake")
        assert taken.run.payload["input"] == {"attempt_id": str(taken.attempt.pk)}
        (asked,) = service.gate.authorized
        assert str(asked.action) == "quiz.retake" and asked.size == {"num_questions": 10, "source_type": "topic"}
        assert queue.runs[-1] == taken.run

    def test_an_open_attempt_is_returned_and_nothing_is_asked_again(self, ready):
        service, quiz = ready
        first = service.retake(quiz)

        again = service.retake(quiz)

        assert not again.created and again.attempt.pk == first.attempt.pk and again.run.pk == first.run.pk
        assert len(service.gate.authorized) == 1

    def test_a_gate_that_refuses_leaves_no_attempt(self, ready, make, queue):
        _, quiz = ready

        with pytest.raises(ActionRefused):
            make(RefusingGate()).retake(quiz)

        assert quiz.attempts.count() == 1

    def test_a_quiz_that_is_not_ready_cannot_be_retaken(self, ready):
        service, quiz = ready
        QuickQuiz.objects.filter(pk=quiz.pk).update(stage="preparing")

        with pytest.raises(WrongStage):
            service.retake(quiz)

    def test_a_quiz_whose_lesson_was_deleted_cannot_be_retaken(self, make, user, make_ready_lesson):
        a = make_ready_lesson("A")
        service = make()
        made = create(service, user, source={"type": "lessons", "lesson_ids": [a.pk]})
        QuickQuiz.objects.filter(pk=made.quiz.pk).update(stage="ready")
        QuickQuizAttempt.objects.filter(pk=made.attempt.pk).update(status="graded")
        a.delete()

        with pytest.raises(SourceMissing):
            service.retake(QuickQuiz.objects.get(pk=made.quiz.pk))

    def test_retakes_are_limited_per_day(self, ready):
        service, quiz = ready
        QuickQuiz.objects.filter(pk=quiz.pk).update(settings_snapshot={**quiz.settings_snapshot, "retakes_per_day": 1})
        service.retake(QuickQuiz.objects.get(pk=quiz.pk))
        QuickQuizAttempt.objects.filter(status="generating").update(status="graded")

        with pytest.raises(RetakeLimitReached):
            service.retake(QuickQuiz.objects.get(pk=quiz.pk))

    def test_the_idempotency_key_reaches_the_gate(self, ready):
        service, quiz = ready

        service.retake(quiz, "retry-1")

        assert service.gate.authorized[0].key.endswith(":retry-1")


class TestDeleting:
    class Threads:
        def __init__(self):
            self.deleted = []

        def delete(self, thread_ids):
            self.deleted += thread_ids

    def test_it_stops_the_runs_settles_the_authorization_erases_and_deletes(self, make, user, queue):
        from quizzes.erasure import QuizErasure

        threads = self.Threads()
        service = make()
        service.erasure = QuizErasure(threads)
        made = create(service, user)
        GraphRun.objects.filter(pk=made.run.pk).update(status="running")
        ModelCall.objects.create(
            quiz_id=made.quiz.pk, node_key="test.generate", provider_key="p", model_name="m", attempt=1,
            fallback_index=0, status="ok", latency_ms=1,
        )  # fmt: skip
        ModelCall.objects.create(
            node_key="test.generate", provider_key="p", model_name="m", attempt=1, fallback_index=0, status="ok",
            latency_ms=1,
        )  # fmt: skip

        quiz_id = made.quiz.pk  # the instance forgets its id when it is deleted

        cancelled = service.delete(made.quiz)

        assert cancelled == [made.run.pk] and not QuickQuiz.objects.filter(pk=quiz_id).exists()
        assert service.gate.settled == [("quiz.create", "cancelled")]
        assert str(quiz_id) in threads.deleted and f"{quiz_id}:{made.run.pk}" not in threads.deleted
        assert ModelCall.objects.filter(quiz_id=quiz_id).count() == 0 and ModelCall.objects.count() == 1
        assert not GraphRun.objects.filter(pk=made.run.pk).exists() and not QuickQuizAttempt.objects.exists()

    def test_another_quizs_data_is_left_alone(self, make, user):
        from quizzes.erasure import QuizErasure

        service = make()
        service.erasure = QuizErasure(self.Threads())
        mine, other = create(service, user), create(service, user, num_questions=15)

        service.delete(mine.quiz)

        assert (
            QuickQuiz.objects.filter(pk=other.quiz.pk).exists()
            and QuickQuizAttempt.objects.filter(pk=other.attempt.pk).exists()
        )
