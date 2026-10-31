"""Unit under test: `lessons.followups`: `FollowupNames` (the deterministic topic of a follow-up) and `FollowupService`
(making a follow-up lesson once).

Why: a follow-up costs a whole lesson, and the spec promises "never a second Foundation lesson", even for a learner who
fails on purpose or double-clicks. The name has to exist before any model runs (so the collision check and the
"already exists" lookup work), and a name that silently re-linked to another of the learner's lessons would attach the
wrong level and history to it. The new lesson must also be a lesson of its own: its own snapshots, its own run, its own
authorization from the gate.

Use cases:
- the topic is "Foundations of X" or "Advanced X", made without a model, from the parent's topic; a parent that is
  itself a
  follow-up (or carries a suffix) gives its plain topic, so names do not pile up
- a name another of the learner's lessons already has gets a suffix, "(2)", "(3)", compared ignoring case and spacing;
  other learners' lessons do not count; the longest topic still fits the limit; an existing lesson is never re-linked
- a follow-up is made from a ready lesson of the learner, once for each level: its entry, origin and level are the
  follow-up's, it points at its parent, carries its own snapshots of the registry and settings, and starts its own run
- a second request for the same level is refused with the id of the lesson that exists, asks the gate nothing, and makes
  nothing; the other level is still allowed
- two requests at the same moment make one lesson (the parent is locked), in real threads and real transactions
- a follow-up carries the parent's note (user_context) and nothing else of its content: no concepts, assessment or plan
- a parent that is not ready makes nothing
- a parent that is only sheets (intent sheets, or a perfect check that chose the sheets) has no test, so it is refused
  with 400 and nothing is asked or made; an Expert lesson chosen after a perfect check is a lesson like any other
- the gate is asked once for lesson.followup, with the level, before anything is created; a refusal creates nothing and
  queues nothing; the authorization completes when the lesson is ready and is stored on the run
- a Foundation follow-up needs the prerequisite planner bound as well as the lesson planner; an Advanced one needs only
  the lesson planner; a missing model creates nothing
- a level other than foundation or advanced is refused
- the follow-up counts as a run starter that the gate meters
"""

import threading

import pytest
from support.gates import CountingGate, RefusingGate

from lessons.errors import FollowupExists, LessonNotConfigured, SheetsOnlyLesson, WrongStage
from lessons.followups import FollowupNames, FollowupService
from lessons.metering import ActionRefused, MeteredAction, RunStarters
from lessons.models import FlowSettings, GraphRun, Lesson, Stage

pytestmark = pytest.mark.django_db


class TestNames:
    def topic(self, parent, level):
        return FollowupNames().topic_for(parent, level)

    @pytest.mark.parametrize(("level", "topic"), [
        ("foundation", "Foundations of Binary search"), ("advanced", "Advanced Binary search"),
    ])  # fmt: skip
    def test_the_topic_is_a_template_of_the_parents(self, lesson, level, topic):
        assert self.topic(lesson, level) == topic

    def test_a_name_another_lesson_has_gets_a_suffix_and_that_lesson_is_not_touched(self, lesson, make_lesson):
        taken = make_lesson(topic="foundations of  binary SEARCH")

        assert self.topic(lesson, "foundation") == "Foundations of Binary search (2)"
        assert Lesson.objects.get(pk=taken.pk).created_from_lesson is None

    def test_suffixes_count_up(self, lesson, make_lesson):
        make_lesson(topic="Advanced Binary search")
        make_lesson(topic="Advanced Binary search (2)")

        assert self.topic(lesson, "advanced") == "Advanced Binary search (3)"

    def test_other_learners_lessons_do_not_count(self, lesson, make_lesson, other_user):
        make_lesson(owner=other_user, topic="Advanced Binary search")

        assert self.topic(lesson, "advanced") == "Advanced Binary search"

    def test_the_longest_topic_still_fits_the_limit_with_a_suffix(self, make_lesson):
        parent = make_lesson(topic="T" * 200)
        make_lesson(topic=self.topic(parent, "foundation"))

        name = self.topic(parent, "foundation")

        assert len(name) <= 200 and name.endswith(" (2)")

    @pytest.mark.parametrize(("parent_topic", "level", "topic"), [
        ("Foundations of Binary search", "advanced", "Advanced Binary search"),
        ("Advanced Binary search", "foundation", "Foundations of Binary search"),
        ("Advanced Binary search (2)", "foundation", "Foundations of Binary search"),
        ("Foundations of Foundations of Sets", "advanced", "Advanced Foundations of Sets"),
    ])  # fmt: skip
    def test_a_follow_up_of_a_follow_up_is_named_for_the_plain_topic(self, make_lesson, parent_topic, level, topic):
        parent = make_lesson(topic=parent_topic, followup_level="foundation")

        assert self.topic(parent, level) == topic

    def test_a_topic_that_only_looks_like_a_template_is_left_alone(self, make_lesson):
        parent = make_lesson(topic="Advanced Placement history")  # not a follow-up

        assert self.topic(parent, "foundation") == "Foundations of Advanced Placement history"

    def test_an_unknown_level_is_refused(self, lesson):
        with pytest.raises(ValueError, match="follow-up level"):
            self.topic(lesson, "intermediate")


@pytest.fixture
def ready(make_lesson):
    return make_lesson(stage=Stage.READY, title="Binary search", level="proficient", settings_snapshot={})


def service(queue, gate=None):
    return FollowupService(queue=queue, gate=gate)


class TestCreate:
    @pytest.mark.parametrize(("level", "topic"), [
        ("foundation", "Foundations of Binary search"), ("advanced", "Advanced Binary search"),
    ])  # fmt: skip
    def test_a_ready_lesson_gets_a_lesson_of_its_own_that_points_back(self, ready, queue, bound_registry, level, topic):
        made, run = service(queue).create(ready, level)

        assert (made.topic, made.owner, made.stage) == (topic, ready.owner, Stage.PREPARING_DIAGNOSTIC)
        assert (made.entry, made.origin, made.intent) == ("followup", "followup", "lesson")
        assert (made.created_from_lesson, made.followup_level) == (ready, level)
        assert made.self_rating_halves is None and made.level == "" and made.pk != ready.pk
        assert made.user_context == ""  # the parent had no note, so the follow-up has none
        assert (
            made.settings_snapshot == FlowSettings.load().snapshot() and "lesson.plan" in made.config_snapshot["nodes"]
        )
        assert (run.lesson, run.graph, run.trigger, run.status) == (
            made, GraphRun.Graph.FLOW, GraphRun.Trigger.START, GraphRun.Status.QUEUED,
        )  # fmt: skip
        assert queue.runs == [run]

    def test_it_carries_the_parents_note_but_not_its_concepts(self, make_lesson, queue, bound_registry):
        parent = make_lesson(
            stage=Stage.READY, user_context="For my exam on Friday.", assessment={"known_concepts": ["loops"]},
            plan={"title": "T"}, settings_snapshot={},
        )  # fmt: skip

        made, _ = service(queue).create(parent, "advanced")

        assert made.user_context == "For my exam on Friday."
        assert made.assessment is None and made.plan is None and made.prerequisites_to_cover == []

    def test_the_parent_is_not_changed(self, ready, queue, bound_registry):
        service(queue).create(ready, "foundation")

        again = Lesson.objects.get(pk=ready.pk)
        assert (again.stage, again.topic, again.created_from_lesson) == (Stage.READY, "Binary search", None)

    def test_both_levels_can_be_made_from_one_lesson(self, ready, queue, bound_registry):
        service(queue).create(ready, "foundation")
        service(queue).create(ready, "advanced")

        assert sorted(ready.followups.values_list("followup_level", flat=True)) == ["advanced", "foundation"]

    @pytest.mark.parametrize("level", ["foundation", "advanced"])
    def test_a_second_request_for_a_level_names_the_lesson_that_exists_and_makes_nothing(
        self, ready, queue, bound_registry, level
    ):
        gate = CountingGate()
        first, _ = service(queue, gate).create(ready, level)

        with pytest.raises(FollowupExists) as caught:
            service(queue, gate).create(ready, level)

        assert caught.value.extra == {"lesson_id": str(first.pk)} and caught.value.status_code == 409
        assert caught.value.default_code == "already_exists"
        assert ready.followups.count() == 1 and len(queue.runs) == 1 and len(gate.authorized) == 1

    def test_a_parent_that_is_not_ready_makes_nothing(self, make_lesson, queue, bound_registry):
        gate = CountingGate()

        for stage in (Stage.GENERATING_LESSON, Stage.FAILED, Stage.AWAITING_CHOICE):
            with pytest.raises(WrongStage):
                service(queue, gate).create(make_lesson(stage=stage), "foundation")

        assert Lesson.objects.filter(followup_level="foundation").count() == 0
        assert gate.authorized == [] and queue.runs == []

    @pytest.mark.parametrize("fields", [{"intent": "sheets"}, {"route": "mastery"}])
    def test_a_lesson_that_is_only_sheets_has_no_test_and_gets_no_followup(
        self, make_lesson, queue, bound_registry, fields
    ):
        gate = CountingGate()
        sheets = make_lesson(stage=Stage.READY, settings_snapshot={}, **fields)

        with pytest.raises(SheetsOnlyLesson) as caught:
            service(queue, gate).create(sheets, "foundation")

        assert caught.value.status_code == 400 and caught.value.default_code == "sheets_only"
        assert Lesson.objects.filter(followup_level="foundation").count() == 0
        assert gate.authorized == [] and queue.runs == []

    def test_an_expert_lesson_chosen_after_a_perfect_check_is_not_sheets_only(self, make_lesson, queue, bound_registry):
        chosen = make_lesson(stage=Stage.READY, route="lesson", settings_snapshot={})

        made, _ = service(queue).create(chosen, "advanced")

        assert made.created_from_lesson == chosen

    def test_an_unknown_level_makes_nothing(self, ready, queue, bound_registry):
        with pytest.raises(ValueError, match="follow-up level"):
            service(queue).create(ready, "intermediate")

        assert ready.followups.count() == 0


class TestTheGate:
    def test_it_is_asked_once_before_anything_exists_with_the_level(self, ready, queue, bound_registry):
        gate = CountingGate()

        made, run = service(queue, gate).create(ready, "foundation", idempotency_key="abc")

        (asked,) = gate.authorized
        assert (asked.action, asked.user, asked.subject_id, asked.resume) == (
            MeteredAction.LESSON_FOLLOWUP, ready.owner, made.pk, False,
        )  # fmt: skip
        assert asked.size == {
            "entry": "followup", "intent": "lesson", "origin": "followup", "covers": "all",
            "followup_level": "foundation",
        }  # fmt: skip
        assert asked.key == f"lesson.followup:{made.pk}:abc"
        assert asked.completes_at.to_payload() == {"kind": "stage", "stage": "ready"}
        assert run.payload["authorization"]["action"] == "lesson.followup"

    def test_a_refusal_creates_nothing_and_queues_nothing(self, ready, queue, bound_registry):
        with pytest.raises(ActionRefused):
            service(queue, RefusingGate()).create(ready, "advanced")

        assert ready.followups.count() == 0 and queue.runs == [] and GraphRun.objects.count() == 0

    def test_it_is_a_metered_run_starter(self):
        assert RunStarters.METERED["FollowupService.create"] is MeteredAction.LESSON_FOLLOWUP


class TestModelsNeeded:
    def unbind(self, key):
        from llm_registry.models import NodeModelBinding

        NodeModelBinding.objects.filter(node__node_key=key).delete()

    def test_an_advanced_followup_needs_only_the_lesson_planner(self, ready, queue, bound_registry):
        self.unbind("prerequisites.plan")
        self.unbind("diagnostic.generate")

        made, _ = service(queue).create(ready, "advanced")

        assert made.followup_level == "advanced"

    def test_a_foundation_followup_needs_the_prerequisite_planner_too(self, ready, queue, bound_registry):
        self.unbind("prerequisites.plan")

        with pytest.raises(LessonNotConfigured, match="prerequisites.plan"):
            service(queue).create(ready, "foundation")

        assert ready.followups.count() == 0

    def test_both_need_the_lesson_planner(self, ready, queue, bound_registry):
        self.unbind("lesson.plan")

        for level in ("foundation", "advanced"):
            with pytest.raises(LessonNotConfigured, match="lesson.plan"):
                service(queue).create(ready, level)


@pytest.mark.django_db(transaction=True)
class TestTwoRequestsAtOnce:
    def test_one_lesson_is_made_and_the_other_request_is_told_which(self, make_lesson, queue, bound_registry):
        parent = make_lesson(stage=Stage.READY)
        gate = CountingGate()
        barrier = threading.Barrier(2)
        outcomes: list = []

        def request():
            barrier.wait()
            try:
                outcomes.append(
                    ("made", service(queue, gate).create(Lesson.objects.get(pk=parent.pk), "foundation")[0].pk)
                )
            except FollowupExists as exc:
                outcomes.append(("exists", exc.extra["lesson_id"]))
            finally:
                from django.db import connection

                connection.close()

        threads = [threading.Thread(target=request) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        made = Lesson.objects.get(created_from_lesson=parent, followup_level="foundation")
        assert sorted(kind for kind, _ in outcomes) == ["exists", "made"]
        assert {str(value) for _, value in outcomes} == {str(made.pk)}
        assert Lesson.objects.filter(created_from_lesson=parent).count() == 1
        assert len(gate.authorized) == 1 and len(queue.runs) == 1
