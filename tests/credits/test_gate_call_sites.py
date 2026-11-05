"""Unit under test: the credit gate (`ACTION_GATE=credits.gate.CreditGate`) at the eight places the lesson and quiz
services
ask it, and across Stop, failure and Retry.

Why: the gate is only worth anything if no costly work can start without it, and if a learner is charged once for
work that
is done and not at all for work that is not. These tests run the real services and the real API with the real gate (the
`credits_on` fixture), and check the thing a learner would notice: a refusal is a 402 that created nothing, and the
credits
follow the work through a pause, a Stop, a failure and a Retry.

Use cases:
- with too few credits each of the eight call sites answers 402 `insufficient_credits` with what is needed and what
  there
  is, and creates no lesson, quiz, attempt, answer or run, and queues nothing: a new lesson, the Quick check handed
  in, the
  mastery choice, an extra sheet, a follow-up, a test retake, a new quick quiz and a quiz retake
- a Quick check handed in with too few credits for the lesson that follows stores nothing, so the learner can send it
  again
  once they have more
- with enough credits each site takes exactly its price, and it comes off the wallet the moment the ask is made
- the whole journey of a lesson (Quick check, then the rest) charges 3 and then 7, each when it starts
- Stop and failure give the credits back; Retry takes them again as a resume, so at most one reserve is live at a
  time and
  the lesson ends charged once; a Retry the learner cannot afford changes nothing and the lesson stays failed
- work that was kept is not charged again on Retry
- a replayed `Idempotency-Key` charges once
- deleting a lesson gives back what was reserved for work under way
- an exempt learner's work is recorded at 0 and never refused
"""

import pytest
from support.lesson_data import make_blueprint_test, make_plan
from support.quiz_data import make_questions
from support.study_data import make_cheat_sheet

from graph.questions.traits import TopicTraits
from lessons.effects import RunEffects
from lessons.metering import AuthorizationSettlement
from lessons.models import GraphRun, Lesson, Quiz, QuizAttempt, Stage, StudyMaterial, TestSubmission
from lessons.services import LessonService
from quizzes.models import QuickQuiz, QuickQuizAttempt
from quizzes.services import QuickQuizService
from quizzes.views import QuizListCreateView, TopicTraitsView

pytestmark = pytest.mark.django_db

QUIZ_BODY = {
    "source": {"type": "topic", "topic": "Binary search"}, "num_questions": 10, "types": ["mcq"],
    "level": {"mode": "self_rating", "rating": 3},
}  # fmt: skip


class Silent:
    def publish(self, run_id, event):
        pass


@pytest.fixture(autouse=True)
def fake_judge(monkeypatch, traits_for):
    judge = traits_for(TopicTraits(quantitative=True, programming=False))
    monkeypatch.setattr(TopicTraitsView, "traits_factory", staticmethod(lambda: judge))
    monkeypatch.setattr(QuizListCreateView, "service_factory", staticmethod(lambda: QuickQuizService(traits=judge)))
    return judge


@pytest.fixture
def poor(credits_on, user):
    """One credit: less than any of the eight actions costs."""
    credits_on.fund(user, 1)
    return credits_on


def refused(response, required, available):
    body = response.json()
    assert response.status_code == 402, body
    assert body["code"] == "insufficient_credits" and (body["required"], body["available"]) == (required, available)


def waiting_quiz(lesson, kind="diagnostic"):
    quiz = Quiz.objects.create(lesson=lesson, kind=kind, questions=make_questions())
    Lesson.objects.filter(pk=lesson.pk).update(
        stage=Stage.AWAITING_DIAGNOSTIC, settings_snapshot={"prereq_trigger_max_correct": 2}
    )
    lesson.refresh_from_db()
    return quiz


def answers(quiz, right):
    return {
        q["id"]: q["correct_index"] if n < right else (q["correct_index"] + 1) % 4 for n, q in enumerate(quiz.questions)
    }


class TestRefusalsCreateNothing:
    def test_a_new_lesson(self, signed_in_client, poor, queue, bound_registry):
        response = signed_in_client.post("/api/lessons", {"topic": "Binary search"}, format="json")

        refused(response, 3, 1)
        assert Lesson.objects.count() == 0 and GraphRun.objects.count() == 0 and queue.runs == []
        assert poor.holds() == []

    def test_a_quick_check_handed_in_stores_nothing(self, signed_in_client, poor, lesson, queue):
        quiz = waiting_quiz(lesson)

        response = signed_in_client.post(
            f"/api/lessons/{lesson.id}/quizzes/diagnostic/attempt", {"answers": answers(quiz, 5)}, format="json"
        )

        refused(response, 7, 1)
        assert QuizAttempt.objects.count() == 0 and GraphRun.objects.count() == 0 and queue.runs == []
        lesson.refresh_from_db()
        assert lesson.stage == Stage.AWAITING_DIAGNOSTIC and poor.holds() == []

    def test_a_quick_check_handed_in_too_poor_can_be_sent_again_once_there_are_credits(
        self, signed_in_client, poor, lesson, queue, user
    ):
        quiz = waiting_quiz(lesson)
        url = f"/api/lessons/{lesson.id}/quizzes/diagnostic/attempt"
        assert signed_in_client.post(url, {"answers": answers(quiz, 5)}, format="json").status_code == 402

        poor.fund(user, 10)
        again = signed_in_client.post(url, {"answers": answers(quiz, 5)}, format="json")

        assert again.status_code == 202 and QuizAttempt.objects.count() == 1 and len(queue.runs) == 1
        assert [h.amount for h in poor.live_holds()] == [7]

    def test_the_mastery_choice(self, signed_in_client, poor, make_lesson, queue):
        lesson = make_lesson(stage=Stage.AWAITING_CHOICE, route="mastery")

        response = signed_in_client.post(f"/api/lessons/{lesson.id}/choice", {"choice": "lesson"}, format="json")

        refused(response, 7, 1)
        assert GraphRun.objects.count() == 0 and queue.runs == []

    def test_an_extra_sheet(self, signed_in_client, poor, make_lesson, queue):
        lesson = make_lesson(stage=Stage.READY, route="mastery")

        response = signed_in_client.post(f"/api/lessons/{lesson.id}/materials", {"kind": "cheat_sheet"}, format="json")

        refused(response, 2, 1)
        assert GraphRun.objects.count() == 0 and queue.runs == []

    def test_a_follow_up(self, signed_in_client, poor, make_lesson, queue, bound_registry):
        lesson = make_lesson(stage=Stage.READY, title="Binary search", settings_snapshot={})

        response = signed_in_client.post(f"/api/lessons/{lesson.id}/followups", {"level": "foundation"}, format="json")

        refused(response, 5, 1)
        assert not Lesson.objects.filter(created_from_lesson=lesson).exists() and queue.runs == []

    def test_a_test_retake(self, signed_in_client, poor, make_lesson, queue):
        test = make_blueprint_test()
        ready = make_lesson(
            stage=Stage.READY, code="x", code_version=1, final_test=test, plan=make_plan(), settings_snapshot={}
        )
        TestSubmission.objects.create(
            lesson=ready, attempt_no=1, status="graded", awarded=14, available=20, questions=test["questions"],
            result={"complete": True, "score": {"awarded": 14, "available": 20, "percent": 0}, "questions": []},
        )  # fmt: skip

        response = signed_in_client.post(f"/api/lessons/{ready.id}/test/attempts")

        refused(response, 2, 1)
        assert TestSubmission.objects.filter(lesson=ready).count() == 1 and queue.runs == []

    def test_a_new_quick_quiz(self, signed_in_client, poor, queue, bound_registry):
        response = signed_in_client.post("/api/quick-quizzes", QUIZ_BODY, format="json")

        refused(response, 2, 1)
        assert QuickQuiz.objects.count() == 0 and QuickQuizAttempt.objects.count() == 0 and queue.runs == []

    def test_a_quiz_retake(self, signed_in_client, poor, make_quiz, make_attempt, queue, bound_registry):
        quiz = make_quiz()
        make_attempt(quiz, status="graded", awarded=1, available=2)

        response = signed_in_client.post(f"/api/quick-quizzes/{quiz.pk}/attempts")

        refused(response, 2, 1)
        assert quiz.attempts.count() == 1 and queue.runs == []


class TestEnoughCreditsPaysThePrice:
    def test_a_new_lesson_takes_its_price_at_once_and_a_replayed_key_charges_once(
        self, signed_in_client, credits_on, user, queue, bound_registry
    ):
        credits_on.fund(user, 20)
        post = lambda: signed_in_client.post(  # noqa: E731
            "/api/lessons", {"topic": "Binary search"}, format="json", HTTP_IDEMPOTENCY_KEY="once"
        )

        first, second = post(), post()

        assert first.status_code == second.status_code == 202 and second.json() == first.json()
        assert credits_on.balance(user) == 17 and [h.amount for h in credits_on.live_holds(user)] == [3]
        assert Lesson.objects.count() == 1 and len(queue.runs) == 1

    def test_a_follow_up_takes_five(self, signed_in_client, credits_on, user, make_lesson, queue, bound_registry):
        credits_on.fund(user, 20)
        lesson = make_lesson(stage=Stage.READY, title="Binary search", settings_snapshot={})

        response = signed_in_client.post(f"/api/lessons/{lesson.id}/followups", {"level": "advanced"}, format="json")

        assert response.status_code == 202 and credits_on.balance(user) == 13

    def test_an_extra_sheet_takes_two_or_three(self, signed_in_client, credits_on, user, make_lesson, queue):
        credits_on.fund(user, 20)
        lesson = make_lesson(stage=Stage.READY, route="mastery")  # no pages: the sheet rests on nothing but the topic

        response = signed_in_client.post(f"/api/lessons/{lesson.id}/materials", {"kind": "cheat_sheet"}, format="json")

        assert response.status_code == 202 and credits_on.balance(user) == 18

    def test_a_quick_quiz_takes_its_tier(self, signed_in_client, credits_on, user, queue, bound_registry):
        credits_on.fund(user, 20)

        response = signed_in_client.post("/api/quick-quizzes", QUIZ_BODY, format="json")

        assert response.status_code == 202 and credits_on.balance(user) == 18

    def test_a_quiz_retake_takes_its_tier(
        self, signed_in_client, credits_on, user, make_quiz, make_attempt, queue, bound_registry
    ):
        credits_on.fund(user, 20)
        quiz = make_quiz()
        make_attempt(quiz, status="graded", awarded=1, available=2)

        response = signed_in_client.post(f"/api/quick-quizzes/{quiz.pk}/attempts")

        assert response.status_code == 202 and credits_on.balance(user) == 18

    def test_a_perfect_quick_check_is_not_charged_until_the_learner_chooses(
        self, signed_in_client, credits_on, user, lesson, queue
    ):
        credits_on.fund(user, 20)
        quiz = waiting_quiz(lesson)

        response = signed_in_client.post(
            f"/api/lessons/{lesson.id}/quizzes/diagnostic/attempt", {"answers": answers(quiz, 10)}, format="json"
        )

        assert response.status_code == 202 and credits_on.balance(user) == 20 and credits_on.holds(user) == []


def service(queue):
    return LessonService(queue=queue, events=Silent())


def effects():
    return RunEffects(settlement=AuthorizationSettlement())


def pause(run, stage, lesson):
    GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.PAUSED)
    Lesson.objects.filter(pk=lesson.pk).update(stage=stage)
    run.refresh_from_db()
    return run


def statuses(credits_on, user):
    return [h.status for h in credits_on.holds(user)]


class TestStopFailureAndRetry:
    def test_the_whole_journey_of_a_lesson_charges_three_then_seven(self, credits_on, user, queue, bound_registry):
        credits_on.fund(user, 20)
        lesson, run = service(queue).create(user, "Binary search")
        assert credits_on.balance(user) == 17

        effects().on_finished(pause(run, Stage.AWAITING_DIAGNOSTIC, lesson))
        assert statuses(credits_on, user) == ["committed"] and credits_on.balance(user) == 17

        from lessons.services import QuizService

        quiz = waiting_quiz(lesson)
        _, resume = QuizService(queue=queue).submit(lesson, "diagnostic", answers(quiz, 5))
        assert credits_on.balance(user) == 10 and statuses(credits_on, user) == ["committed", "held"]

        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.READY)
        GraphRun.objects.filter(pk=resume.pk).update(status=GraphRun.Status.SUCCEEDED)
        resume.refresh_from_db()
        effects().on_finished(resume, ended=True)

        assert statuses(credits_on, user) == ["committed", "committed"] and credits_on.balance(user) == 10

    def test_stop_releases_and_retry_takes_the_credits_again_so_the_lesson_is_charged_once(
        self, credits_on, user, queue, bound_registry
    ):
        credits_on.fund(user, 20)
        svc = service(queue)
        lesson, run = svc.create(user, "Binary search")
        GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.RUNNING)
        run.refresh_from_db()

        svc.cancel(run)  # Stop
        lesson.refresh_from_db()
        assert statuses(credits_on, user) == ["released"] and credits_on.balance(user) == 20

        retry = svc.retry(lesson)

        assert statuses(credits_on, user) == ["released", "held"] and credits_on.balance(user) == 17
        assert len(credits_on.live_holds(user)) == 1 and retry.payload["authorization"]["resume"] is True
        effects().on_finished(pause(retry, Stage.AWAITING_DIAGNOSTIC, lesson))
        assert statuses(credits_on, user) == ["released", "committed"] and credits_on.balance(user) == 17

    def test_repeated_stops_and_retries_never_leave_two_live_reserves(self, credits_on, user, queue, bound_registry):
        credits_on.fund(user, 20)
        svc = service(queue)
        lesson, run = svc.create(user, "Binary search")

        for _ in range(3):
            GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.RUNNING)
            run.refresh_from_db()
            svc.cancel(run)
            lesson.refresh_from_db()
            assert credits_on.live_holds(user) == [] and credits_on.balance(user) == 20
            run = svc.retry(lesson)
            assert len(credits_on.live_holds(user)) == 1 and credits_on.balance(user) == 17

        assert statuses(credits_on, user) == ["released"] * 3 + ["held"]

    def test_a_failure_releases_and_retry_takes_it_again(self, credits_on, user, queue, bound_registry):
        credits_on.fund(user, 20)
        svc = service(queue)
        lesson, run = svc.create(user, "Binary search")
        GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.RUNNING)
        run.refresh_from_db()

        effects().on_stopped(run, "Every AI model failed.")
        GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.FAILED)
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.FAILED, error="boom")
        lesson.refresh_from_db()
        assert statuses(credits_on, user) == ["released"] and credits_on.balance(user) == 20

        svc.retry(lesson)

        assert statuses(credits_on, user) == ["released", "held"] and credits_on.balance(user) == 17

    def test_a_retry_the_learner_cannot_afford_changes_nothing_and_the_lesson_stays_failed(
        self, credits_on, user, queue, bound_registry
    ):
        from credits.models import CreditBucket
        from credits.refusals import InsufficientCredits

        credits_on.fund(user, 3)
        svc = service(queue)
        lesson, run = svc.create(user, "Binary search")
        GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.RUNNING)
        run.refresh_from_db()
        svc.cancel(run)
        lesson.refresh_from_db()
        CreditBucket.objects.filter(user=user).update(amount_remaining=1, amount_granted=1)  # spent elsewhere meanwhile
        runs, queued = GraphRun.objects.count(), len(queue.runs)

        with pytest.raises(InsufficientCredits):
            svc.retry(lesson)

        lesson.refresh_from_db()
        assert lesson.stage == Stage.FAILED and GraphRun.objects.count() == runs and len(queue.runs) == queued

    def test_work_that_was_kept_is_not_charged_again_on_retry(self, credits_on, user, queue, bound_registry):
        credits_on.fund(user, 20)
        svc = service(queue)
        lesson, run = svc.create(user, "Binary search")
        effects().on_finished(pause(run, Stage.AWAITING_DIAGNOSTIC, lesson))  # the quiz was served: kept
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.FAILED, error="boom")
        lesson.refresh_from_db()

        svc.retry(lesson)

        assert statuses(credits_on, user) == ["committed"] and credits_on.balance(user) == 17

    def test_deleting_a_lesson_gives_back_what_was_reserved_for_work_under_way(
        self, credits_on, user, queue, bound_registry
    ):
        credits_on.fund(user, 20)
        svc = service(queue)
        lesson, run = svc.create(user, "Binary search")
        GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.RUNNING)

        svc.delete(lesson)

        assert statuses(credits_on, user) == ["released"] and credits_on.balance(user) == 20

    def test_deleting_a_lesson_whose_work_was_done_keeps_the_charge(self, credits_on, user, queue, bound_registry):
        credits_on.fund(user, 20)
        svc = service(queue)
        lesson, run = svc.create(user, "Binary search")
        effects().on_finished(pause(run, Stage.AWAITING_DIAGNOSTIC, lesson))

        svc.delete(lesson)

        assert statuses(credits_on, user) == ["committed"] and credits_on.balance(user) == 17


class TestAnExemptLearner:
    def test_is_never_refused_and_is_recorded_at_zero(self, signed_in_client, credits_on, user, queue, bound_registry):
        from credits.ledger import Ledger
        from credits.models import CreditTransaction, Wallet

        Wallet.objects.create(user=user, credits_exempt=True, created_at=Ledger().clock.now())

        response = signed_in_client.post("/api/lessons", {"topic": "Binary search"}, format="json")

        assert response.status_code == 202 and credits_on.balance(user) == 0
        (hold,) = credits_on.holds(user)
        assert (hold.amount, hold.exempt) == (0, True) and hold.lines[0]["credits"] == 3
        assert list(CreditTransaction.objects.filter(user=user).values_list("type", "amount")) == [("hold", 0)]


def test_the_sheet_a_lesson_made_of_sheets_asks_for_later_costs_two(credits_on, user, make_lesson, queue):
    """K11: a sheet added later to a sheets-only lesson from a Quick check rests on the quiz, and costs 2."""
    from lessons.services import MaterialService

    credits_on.fund(user, 10)
    lesson = make_lesson(stage=Stage.READY, intent="sheets", entry="diagnostic", route="mastery")
    StudyMaterial.objects.create(lesson=lesson, kind="cheat_sheet", content=make_cheat_sheet())

    MaterialService(queue=queue).request_extra(lesson, "revision_sheet")

    assert credits_on.balance(user) == 8
