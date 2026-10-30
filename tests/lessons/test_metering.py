"""Unit under test: `lessons.metering`, the extension seam that lets a later pricing feature say yes or no to every
action that starts paid model work, and be told how the work ended (`MeteredAction`, `CompletionPoint`,
`ActionContext`, `Authorization`, `ActionGate`, `OpenGate`, `ActionRefused`, `ActionMetering`).

Why: metering is cheap to build in now and expensive to retrofit. If the seam asks twice, asks after a row exists,
forgets to release on failure, or changes what the app does when nothing is metered, a later system would
double-charge, charge for nothing, or break lesson creation. The default gate must leave the app exactly as it was.

Use cases:
- the seven action keys are the ones in the plan, and each is a string
- a completion point is reached at its stage or when the run ended, never earlier; a run-end point only at the end
- every action wired today has a completion point; one that is not wired yet says so
- a lesson created by self-rating covers the whole lesson, so it completes when the lesson is ready, where a quick check
  completes when the quiz is served
- an authorization round-trips through the run payload and keeps what it was asked with
- the open gate allows everything, settles nothing, and is not stored on the run, so payloads stay as they were
- the gate class comes from the `ACTION_GATE` setting
- a refusal is an API error with a code and a readable message
- the facade builds the context: the action's completion point, a key made of the action and subject (plus the resume
  number or the client's key), and `resume` for an ask made again
- an ask that fails after the gate said yes is released as failed, and one that succeeds is left alone
- a payload carries the open authorization forward to a continuation run, and nothing once it is settled
- asking again after Stop or failure reads the action and size from the last flow run, only when it was released
- every service method that queues a run is classified as metered, resuming or never metered
"""

import ast
import pathlib

import pytest
from django.test import override_settings
from rest_framework.exceptions import APIException
from support.gates import CountingGate, RefusingGate

from lessons import attempts, followups, services
from lessons.metering import (
    ActionContext,
    ActionGates,
    ActionMetering,
    ActionRefused,
    Authorization,
    CompletionPoint,
    CompletionPoints,
    MeteredAction,
    OpenGate,
    RunOutcome,
    RunStarters,
)
from lessons.models import GraphRun
from lessons.stages import Stage

pytestmark = pytest.mark.django_db

LESSON_CREATE, LESSON_CONTINUE, SHEET_GENERATE = (
    MeteredAction.LESSON_CREATE,
    MeteredAction.LESSON_CONTINUE,
    MeteredAction.SHEET_GENERATE,
)


def run_for(lesson, authorization=None, settled=None, status=GraphRun.Status.FAILED, trigger=GraphRun.Trigger.START):
    payload = {}
    if authorization:
        payload["authorization"] = {**authorization.to_payload(), "settled": settled}
    return GraphRun.objects.create(lesson=lesson, trigger=trigger, status=status, payload=payload)


def context(action=LESSON_CREATE, **fields):
    defaults = {"user": None, "size": {}, "subject_id": "s1", "key": "k", "resume": False}
    return ActionContext(action=action, completes_at=CompletionPoints.of(action), **(defaults | fields))


class TestActions:
    def test_the_seven_action_keys_are_the_ones_in_the_plan(self):
        assert [str(action) for action in MeteredAction] == [
            "lesson.create", "lesson.continue", "lesson.followup", "test.retake",
            "quiz.create", "quiz.retake", "sheet.generate",
        ]  # fmt: skip
        assert MeteredAction("lesson.create") is LESSON_CREATE


class TestCompletionPoint:
    def test_a_stage_point_is_reached_at_that_stage_or_when_the_run_ended(self):
        point = CompletionPoint.at_stage(Stage.READY)

        assert not point.reached(Stage.GENERATING_LESSON, ended=False)
        assert not point.reached(Stage.AWAITING_PREREQUISITE, ended=False)
        assert point.reached(Stage.READY, ended=False)
        assert point.reached(Stage.GENERATING_LESSON, ended=True)

    def test_a_run_end_point_is_reached_only_when_the_run_ended(self):
        point = CompletionPoint.at_run_end()

        assert not point.reached(Stage.READY, ended=False)
        assert point.reached(Stage.READY, ended=True)

    def test_a_point_round_trips_through_a_payload(self):
        for point in (CompletionPoint.at_stage(Stage.AWAITING_DIAGNOSTIC), CompletionPoint.at_run_end()):
            assert CompletionPoint.from_payload(point.to_payload()) == point

    @pytest.mark.parametrize(
        ("action", "point"),
        [
            (LESSON_CREATE, CompletionPoint.at_stage(Stage.AWAITING_DIAGNOSTIC)),
            (LESSON_CONTINUE, CompletionPoint.at_stage(Stage.READY)),
            (SHEET_GENERATE, CompletionPoint.at_run_end()),
            (MeteredAction.TEST_RETAKE, CompletionPoint.at_run_end()),  # the retake run ends as the attempt starts
        ],
    )
    def test_every_action_wired_today_has_a_completion_point(self, action, point):
        assert CompletionPoints.of(action) == point

    @pytest.mark.parametrize(("size", "point"), [
        ({"covers": "diagnostic"}, CompletionPoint.at_stage(Stage.AWAITING_DIAGNOSTIC)),
        ({"covers": "all"}, CompletionPoint.at_stage(Stage.READY)),
        ({}, CompletionPoint.at_stage(Stage.AWAITING_DIAGNOSTIC)),
    ])  # fmt: skip
    def test_a_lesson_that_covers_everything_completes_when_it_is_ready(self, size, point):
        assert CompletionPoints.of(LESSON_CREATE, size) == point

    def test_the_size_changes_no_other_actions_point(self):
        assert CompletionPoints.of(LESSON_CONTINUE, {"covers": "all"}) == CompletionPoint.at_stage(Stage.READY)
        assert CompletionPoints.of(SHEET_GENERATE, {"covers": "all"}) == CompletionPoint.at_run_end()

    def test_an_action_that_is_not_wired_yet_says_so(self):
        with pytest.raises(LookupError, match="quiz.create"):
            CompletionPoints.of(MeteredAction.QUIZ_CREATE)


class TestAuthorization:
    def test_round_trips_through_the_run_payload_with_what_it_was_asked_with(self):
        ask = context(LESSON_CONTINUE, size={"choice": "lesson", "perfect": False}, resume=True)

        authorization = Authorization.of(ask, meta={"hold": "h1"})
        again = Authorization.from_payload(authorization.to_payload())

        assert again == authorization
        assert (again.action, again.size, again.resume, again.meta) == (
            LESSON_CONTINUE, {"choice": "lesson", "perfect": False}, True, {"hold": "h1"},
        )  # fmt: skip
        assert again.completes_at == CompletionPoints.of(LESSON_CONTINUE)

    def test_each_authorization_has_its_own_id(self):
        assert Authorization.of(context()).id != Authorization.of(context()).id


class TestOpenGate:
    def test_allows_everything_and_settles_nothing(self):
        gate = OpenGate()

        authorization = gate.authorize(context())

        assert authorization.action == LESSON_CREATE
        for outcome in RunOutcome:
            assert gate.settle(authorization, outcome) is None

    def test_what_it_allows_is_not_stored_on_the_run(self, lesson):
        authorization = OpenGate().authorize(context())

        assert ActionMetering(OpenGate()).payload(authorization) == {}


class TestSetting:
    def test_the_default_gate_is_the_open_one(self):
        assert isinstance(ActionGates.default(), OpenGate)

    @override_settings(ACTION_GATE="support.gates.CountingGate")
    def test_the_gate_class_comes_from_the_setting(self):
        assert isinstance(ActionGates.default(), CountingGate)


class TestRefusal:
    def test_is_an_api_error_with_a_code_and_a_readable_message(self):
        refusal = ActionRefused("You cannot do that now.", code="not_now")

        assert isinstance(refusal, APIException)
        assert (refusal.detail, refusal.get_codes()) == ("You cannot do that now.", "not_now")

    def test_has_a_default_code_and_message(self):
        refusal = ActionRefused()

        assert refusal.get_codes() == "action_refused" and str(refusal.detail)


class TestActionMetering:
    def test_builds_the_context_the_gate_sees(self, lesson, user):
        gate = CountingGate()

        authorization = ActionMetering(gate).authorize(
            user, LESSON_CREATE, size={"entry": "diagnostic"}, subject_id=lesson.id
        )

        (asked,) = gate.authorized
        assert asked.user == user and asked.action == LESSON_CREATE and asked.size == {"entry": "diagnostic"}
        assert asked.subject_id == lesson.id and asked.resume is False
        assert asked.completes_at == CompletionPoints.of(LESSON_CREATE)
        assert asked.key == f"lesson.create:{lesson.id}"
        assert authorization.action == LESSON_CREATE

    def test_the_gate_is_told_a_self_rated_lessons_point_is_the_whole_lesson(self, lesson, user):
        gate = CountingGate()

        ActionMetering(gate).authorize(
            user, LESSON_CREATE, size={"entry": "self_rating", "covers": "all"}, subject_id=lesson.id
        )

        assert gate.authorized[0].completes_at == CompletionPoint.at_stage(Stage.READY)

    def test_the_key_carries_the_clients_idempotency_key(self, lesson, user):
        gate = CountingGate()

        ActionMetering(gate).authorize(user, LESSON_CREATE, size={}, subject_id=lesson.id, client_key="abc")

        assert gate.authorized[0].key == f"lesson.create:{lesson.id}:abc"

    def test_the_key_of_an_ask_made_again_carries_the_resume_number(self, lesson, user):
        gate = CountingGate()
        metering = ActionMetering(gate)
        first = run_for(lesson, Authorization.of(context(subject_id=str(lesson.id))), settled="cancelled")
        assert first.pk

        metering.authorize(user, LESSON_CREATE, size={}, subject_id=lesson.id, resume=True)

        asked = gate.authorized[0]
        assert asked.resume is True and asked.key == f"lesson.create:{lesson.id}:resume1"

    def test_a_refusal_propagates_and_nothing_is_stored(self, lesson, user):
        with pytest.raises(ActionRefused):
            ActionMetering(RefusingGate()).authorize(user, LESSON_CREATE, size={}, subject_id=lesson.id)

        assert GraphRun.objects.count() == 0

    def test_an_ask_that_fails_after_the_gate_said_yes_is_released_as_failed(self, lesson, user):
        gate = CountingGate()
        metering = ActionMetering(gate)
        authorization = metering.authorize(user, LESSON_CREATE, size={}, subject_id=lesson.id)

        with pytest.raises(RuntimeError), metering.guard(authorization):
            raise RuntimeError("the insert failed")

        assert gate.settled == [("lesson.create", RunOutcome.FAILED)]

    def test_an_ask_that_goes_through_is_not_released(self, lesson, user):
        gate = CountingGate()
        metering = ActionMetering(gate)
        authorization = metering.authorize(user, LESSON_CREATE, size={}, subject_id=lesson.id)

        with metering.guard(authorization):
            pass

        assert gate.settled == []

    def test_the_payload_of_a_tracked_authorization_holds_it(self, user):
        authorization = Authorization.of(context())

        payload = ActionMetering(CountingGate()).payload(authorization)

        assert Authorization.from_payload(payload["authorization"]) == authorization


class TestCarryAndAskAgain:
    def test_carries_the_open_authorization_to_a_continuation_run(self, lesson):
        authorization = Authorization.of(context(LESSON_CONTINUE))
        run_for(lesson, authorization, settled=None, status=GraphRun.Status.PAUSED)

        carried = ActionMetering(CountingGate()).carry(lesson)

        assert Authorization.from_payload(carried["authorization"]) == authorization
        assert carried["authorization"].get("settled") is None

    @pytest.mark.parametrize("settled", ["succeeded", "failed", "cancelled"])
    def test_carries_nothing_once_it_is_settled(self, lesson, settled):
        run_for(lesson, Authorization.of(context(LESSON_CONTINUE)), settled=settled)

        assert ActionMetering(CountingGate()).carry(lesson) == {}

    def test_carries_nothing_when_no_run_has_one(self, lesson):
        run_for(lesson)

        assert ActionMetering(CountingGate()).carry(lesson) == {}

    @pytest.mark.parametrize("settled", ["failed", "cancelled"])
    def test_asks_again_for_the_action_and_size_of_a_released_run(self, lesson, user, settled):
        gate = CountingGate()
        size = {"choice": "lesson", "perfect": False}
        run_for(lesson, Authorization.of(context(LESSON_CONTINUE, size=size)), settled=settled)

        authorization = ActionMetering(gate).ask_again(lesson)

        (asked,) = gate.authorized
        assert (asked.action, asked.size, asked.resume) == (LESSON_CONTINUE, size, True)
        assert asked.user == user and authorization.resume is True

    def test_does_not_ask_again_for_work_that_was_kept(self, lesson):
        gate = CountingGate()
        run_for(lesson, Authorization.of(context(LESSON_CREATE)), settled="succeeded")

        assert ActionMetering(gate).ask_again(lesson) is None
        assert gate.authorized == []

    def test_does_not_ask_when_the_last_run_had_no_authorization(self, lesson):
        gate = CountingGate()
        run_for(lesson)

        assert ActionMetering(gate).ask_again(lesson) is None
        assert gate.authorized == []

    def test_an_authorization_that_was_never_settled_is_released_before_asking_again(self, lesson):
        gate = CountingGate()
        run_for(lesson, Authorization.of(context(LESSON_CREATE)), settled=None)

        ActionMetering(gate).ask_again(lesson)

        assert gate.settled == [("lesson.create", RunOutcome.FAILED)]
        assert len(gate.authorized) == 1

    def test_asks_only_about_the_last_flow_run(self, lesson):
        gate = CountingGate()
        run_for(lesson, Authorization.of(context(LESSON_CREATE)), settled="cancelled")
        run_for(lesson, None, trigger=GraphRun.Trigger.RETRY)  # a later flow run without one

        assert ActionMetering(gate).ask_again(lesson) is None


class TestSettleOpen:
    def test_settles_the_open_authorization_with_the_outcome(self, lesson):
        gate = CountingGate()
        run = run_for(lesson, Authorization.of(context(LESSON_CONTINUE)), settled=None, status=GraphRun.Status.PAUSED)

        ActionMetering(gate).settle_open(lesson, RunOutcome.CANCELLED)

        assert gate.settled == [("lesson.continue", RunOutcome.CANCELLED)]
        run.refresh_from_db()
        assert run.payload["authorization"]["settled"] == "cancelled"

    def test_settles_nothing_that_is_already_settled(self, lesson):
        gate = CountingGate()
        run_for(lesson, Authorization.of(context(LESSON_CREATE)), settled="succeeded")

        ActionMetering(gate).settle_open(lesson, RunOutcome.CANCELLED)

        assert gate.settled == []


class TestEveryRunStarterIsClassified:
    SERVICES = (pathlib.Path(services.__file__), pathlib.Path(attempts.__file__), pathlib.Path(followups.__file__))

    def run_starters(self) -> set[str]:
        """`Class.method` for every method in the services that hands a run to the dispatcher."""
        found = set()
        for path in self.SERVICES:
            for node in ast.parse(path.read_text()).body:
                if isinstance(node, ast.ClassDef) and node.name != "RunDispatcher":
                    for method in [m for m in node.body if isinstance(m, ast.FunctionDef)]:
                        calls = [
                            c for c in ast.walk(method) if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                        ]
                        if any(call.func.attr == "dispatch" for call in calls):
                            found.add(f"{node.name}.{method.name}")
        return found

    def test_each_service_method_that_queues_a_run_is_metered_resuming_or_never_metered(self):
        classified = set(RunStarters.METERED) | set(RunStarters.RESUMING) | set(RunStarters.NEVER)

        assert self.run_starters() <= classified
        assert classified <= self.run_starters()  # and nothing in the lists is stale

    def test_the_lists_do_not_overlap_and_the_metered_ones_name_an_action(self):
        everything = [*RunStarters.METERED, *RunStarters.RESUMING, *RunStarters.NEVER]

        assert len(everything) == len(set(everything))
        assert all(isinstance(action, MeteredAction) for action in RunStarters.METERED.values())
        assert all(RunStarters.NEVER.values())  # every never-metered method says why
