"""Unit under test: what counts as study, at the places the services report it (credits plan T16): a metered action that
succeeded (`CreditGate.settle`), and a test, a quick quiz or a Quick check that was handed in. Run with the real
services,
the real gate and `CreditsActivitySink` (the `credits_on` fixture switches both on).

Why: the daily credit and the streak are only worth anything if they cannot be farmed. A request that is refused,
fails, is
cancelled, is merely begun, or hands in nothing must earn nothing, or a learner could collect the day's credit with a
request that learns nothing. And the study that does count has to count once.

Use cases:
- an action refused for lack of credits earns nothing (and creates nothing)
- an action that has only been asked for (its credits reserved, its work under way) earns nothing yet
- an action whose run failed or was stopped earns nothing, and neither does a second ask that is refused
- an action that succeeded earns the day, at the day it was asked, in the learner's zone; a free action and an exempt
  learner's action count too
- a test handed in earns the day; a test handed in with every answer blank does not; a test only started does not
- a quick quiz handed in earns the day; a blank one does not
- a Quick check handed in earns the day; one of only "I don't know" does not
- doing several of these in a day earns the day's credit once
- with the default sink (`ACTIVITY_SINK` unchanged) none of this earns anything
"""

import pytest
from support.lesson_data import make_blueprint_test, make_plan
from support.question_data import make_question
from support.quiz_data import make_questions

from credits.models import CreditBucket, StreakDay, Wallet
from lessons.effects import RunEffects
from lessons.metering import AuthorizationSettlement
from lessons.models import GraphRun, Lesson, Quiz, Stage, TestSubmission
from lessons.services import LessonService

pytestmark = pytest.mark.django_db

TEST = make_blueprint_test()


class Silent:
    def publish(self, run_id, event):
        pass


@pytest.fixture
def earning(earning_on):
    return earning_on


def days_of(user) -> int:
    return StreakDay.objects.filter(user=user).count()


def daily(user) -> int:
    return sum(b.amount_granted for b in CreditBucket.objects.filter(user=user, source="daily"))


def service(queue):
    return LessonService(queue=queue, events=Silent())


def pause(run, stage, lesson):
    GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.PAUSED)
    Lesson.objects.filter(pk=lesson.pk).update(stage=stage)
    run.refresh_from_db()
    return run


class TestAMeteredAction:
    def test_a_refusal_earns_nothing(self, signed_in_client, earning, user, queue, bound_registry):
        response = signed_in_client.post("/api/lessons", {"topic": "Binary search"}, format="json")

        assert response.status_code == 402 and days_of(user) == 0 and daily(user) == 0

    def test_an_action_only_asked_for_earns_nothing_yet(self, earning, user, queue, bound_registry):
        earning.fund(user, 20)

        service(queue).create(user, "Binary search")

        assert days_of(user) == 0 and daily(user) == 0

    @pytest.mark.parametrize("how", ["failed", "stopped"])
    def test_an_action_whose_run_failed_or_was_stopped_earns_nothing(self, earning, user, queue, bound_registry, how):
        earning.fund(user, 20)
        svc = service(queue)
        lesson, run = svc.create(user, "Binary search")
        GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.RUNNING)
        run.refresh_from_db()

        if how == "stopped":
            svc.cancel(run)
        else:
            RunEffects(settlement=AuthorizationSettlement()).on_stopped(run, "Every AI model failed.")

        assert days_of(user) == 0 and daily(user) == 0

    def test_an_action_that_succeeded_earns_the_day(self, earning, user, queue, bound_registry):
        earning.fund(user, 20)
        lesson, run = service(queue).create(user, "Binary search")

        RunEffects(settlement=AuthorizationSettlement()).on_finished(pause(run, Stage.AWAITING_DIAGNOSTIC, lesson))

        assert days_of(user) == 1 and daily(user) == 1

    def test_the_day_is_the_day_it_was_asked(self, earning, user, queue, bound_registry):
        from credits.models import CreditHold

        earning.fund(user, 20)
        lesson, run = service(queue).create(user, "Binary search")
        hold = CreditHold.objects.get(user=user)
        from credits.earning.localday import LocalDay

        asked_on = LocalDay.of(hold.created_at, "Asia/Kolkata").date

        RunEffects(settlement=AuthorizationSettlement()).on_finished(pause(run, Stage.AWAITING_DIAGNOSTIC, lesson))

        assert StreakDay.objects.get(user=user).local_date == asked_on

    def test_a_free_action_counts_too(self, earning, user, make_lesson, queue):
        from lessons.services import MaterialService

        earning.fund(user, 5)
        lesson = make_lesson(stage=Stage.READY, intent="sheets", entry="diagnostic", route="mastery")
        run = MaterialService(queue=queue).request_extra(lesson, "cheat_sheet")  # 2 credits
        GraphRun.objects.filter(pk=run.pk).update(status=GraphRun.Status.SUCCEEDED)
        run.refresh_from_db()

        RunEffects(settlement=AuthorizationSettlement()).on_finished(run, ended=True)

        assert days_of(user) == 1

    def test_an_exempt_learners_action_counts(self, earning, user, queue, bound_registry):
        from credits.ledger import Ledger

        Wallet.objects.create(user=user, credits_exempt=True, created_at=Ledger().clock.now())
        lesson, run = service(queue).create(user, "Binary search")

        RunEffects(settlement=AuthorizationSettlement()).on_finished(pause(run, Stage.AWAITING_DIAGNOSTIC, lesson))

        assert days_of(user) == 1


def ready(make_lesson):
    return make_lesson(
        stage=Stage.READY, code="x", code_version=1, final_test=TEST, plan=make_plan(), settings_snapshot={}
    )


class TestATestHandedIn:
    def start(self, signed_in_client, lesson):
        return signed_in_client.post(f"/api/lessons/{lesson.id}/test/attempts").json()

    def test_a_test_handed_in_earns_the_day(self, signed_in_client, earning, user, make_lesson):
        lesson = ready(make_lesson)
        attempt = self.start(signed_in_client, lesson)

        signed_in_client.post(
            f"/api/lessons/{lesson.id}/test/attempts/{attempt['attempt_id']}/submit",
            {"answers": {"t1": TEST["questions"][0]["correct_index"]}},
            format="json",
        )

        assert days_of(user) == 1 and daily(user) == 1

    def test_a_test_only_started_earns_nothing(self, signed_in_client, earning, user, make_lesson):
        self.start(signed_in_client, ready(make_lesson))

        assert days_of(user) == 0

    def test_a_blank_test_earns_nothing(self, signed_in_client, earning, user, make_lesson):
        lesson = ready(make_lesson)
        attempt = self.start(signed_in_client, lesson)

        response = signed_in_client.post(
            f"/api/lessons/{lesson.id}/test/attempts/{attempt['attempt_id']}/submit", {"answers": {}}, format="json"
        )

        assert response.status_code == 200 and days_of(user) == 0
        assert TestSubmission.objects.get(pk=attempt["attempt_id"]).all_blank is True


class TestAQuickQuiz:
    QUESTIONS = [make_question("mcq", 1, "easy"), make_question("msq", 2, "basic")]

    def taking(self, quiz, make_attempt):
        return make_attempt(quiz, status="in_progress", questions=self.QUESTIONS)

    def test_a_quiz_handed_in_earns_the_day(self, signed_in_client, earning, user, quiz, make_attempt):
        attempt = self.taking(quiz, make_attempt)

        signed_in_client.post(
            f"/api/quick-quizzes/{quiz.pk}/attempts/{attempt.pk}/submit", {"answers": {"t1": 1}}, format="json"
        )

        assert days_of(user) == 1 and daily(user) == 1

    def test_a_blank_quiz_earns_nothing(self, signed_in_client, earning, user, quiz, make_attempt):
        attempt = self.taking(quiz, make_attempt)

        signed_in_client.post(
            f"/api/quick-quizzes/{quiz.pk}/attempts/{attempt.pk}/submit", {"answers": {"t1": None}}, format="json"
        )

        assert days_of(user) == 0


class TestAQuickCheck:
    def waiting(self, lesson):
        quiz = Quiz.objects.create(lesson=lesson, kind="diagnostic", questions=make_questions())
        Lesson.objects.filter(pk=lesson.pk).update(
            stage=Stage.AWAITING_DIAGNOSTIC, settings_snapshot={"prereq_trigger_max_correct": 2}
        )
        return quiz

    def test_a_check_handed_in_earns_the_day(self, signed_in_client, earning, user, lesson, queue):
        earning.fund(user, 20)
        quiz = self.waiting(lesson)
        answers = {
            q["id"]: q["correct_index"] if n < 5 else (q["correct_index"] + 1) % 4 for n, q in enumerate(quiz.questions)
        }

        response = signed_in_client.post(
            f"/api/lessons/{lesson.id}/quizzes/diagnostic/attempt", {"answers": answers}, format="json"
        )

        assert response.status_code == 202 and days_of(user) == 1

    def test_a_check_of_only_i_dont_know_earns_nothing(self, signed_in_client, earning, user, lesson, queue):
        earning.fund(user, 20)
        quiz = self.waiting(lesson)

        signed_in_client.post(
            f"/api/lessons/{lesson.id}/quizzes/diagnostic/attempt",
            {"answers": {q["id"]: "dont_know" for q in quiz.questions}},
            format="json",
        )

        assert days_of(user) == 0


def test_several_kinds_of_study_in_a_day_earn_the_credit_once(
    signed_in_client, earning, user, make_lesson, quiz, make_attempt
):
    lesson = ready(make_lesson)
    attempt = signed_in_client.post(f"/api/lessons/{lesson.id}/test/attempts").json()
    signed_in_client.post(
        f"/api/lessons/{lesson.id}/test/attempts/{attempt['attempt_id']}/submit",
        {"answers": {"t1": TEST["questions"][0]["correct_index"]}},
        format="json",
    )
    taking = make_attempt(quiz, status="in_progress", questions=[make_question("mcq", 1, "easy")])
    signed_in_client.post(
        f"/api/quick-quizzes/{quiz.pk}/attempts/{taking.pk}/submit", {"answers": {"t1": 1}}, format="json"
    )

    assert days_of(user) == 1 and daily(user) == 1


def test_with_the_default_sink_none_of_it_earns_anything(signed_in_client, credits_on, user, make_lesson):
    lesson = ready(make_lesson)
    attempt = signed_in_client.post(f"/api/lessons/{lesson.id}/test/attempts").json()

    signed_in_client.post(
        f"/api/lessons/{lesson.id}/test/attempts/{attempt['attempt_id']}/submit",
        {"answers": {"t1": TEST["questions"][0]["correct_index"]}},
        format="json",
    )

    assert days_of(user) == 0
