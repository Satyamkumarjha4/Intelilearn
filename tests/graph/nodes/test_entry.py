"""Unit under test: the way into a lesson for a learner who took no quick check (`graph.nodes.entry`): the three routers
that decide (`EntryRouter`, `LevelGate`, `IntentRouter`), the junction nodes they hang on, `assess_from_source`,
`plan_prerequisites` and `validate_prerequisites`.

Why: a self-rated lesson has no quiz behind its level, so these steps must do in code what the quiz did: turn the rating
into the one assessment, move the lesson to building, and make sure a Beginner (who was not tested) still gets the
prerequisites taught. A router that sends a quick-check learner through the planner would charge for nothing; one that
skips a Beginner would write a lesson that assumes what they lack.

Use cases:
- the entry router sends the quick check (and a thread from before self-rating, which has no entry) to the quiz and any
  other entry to its assessment source
- the level gate plans prerequisites for a Beginner who took no quiz, and for no one else: not a quick check, not a
  level above Beginner, not a lesson that already has prerequisites
- the level gate reads the level by the scheme the assessment was written under
- the level gate plans nothing for a lesson that asked for sheets only, whatever the level: there is no lesson to
  prepare for
- the intent router sends a lesson on, sheets to the sheets writer, treats a missing intent as a lesson, and refuses an
  intent that is not wired
- the junction nodes change nothing
- assess_from_source turns the rating into the assessment, records it on the lesson with the level, the level source,
  the lesson route and no prerequisites, and moves the lesson from the quiz stage to building
- assess_from_source for a lesson that asked for sheets moves it to writing sheets, records no lesson route, and leaves
  the level and the source as for any rating
- assess_from_source takes a follow-up's level from what it is for and records the test score as the level source
- assess_from_source recovers a failed lesson to building, and refuses an entry that has no source
- plan_prerequisites asks the model for a prerequisite list and counts the attempt
- validate_prerequisites accepts a good list: it becomes the lesson's prerequisites, on the lesson and in the
  assessment's names; a bad list asks for another attempt with the problems; and one that stays bad gives up with a
  readable error that retries at plan_prerequisites
"""

import pytest

from graph.errors import RunFailed
from graph.levels import LevelScheme
from graph.nodes.entry import (
    AssessFromSourceNode,
    EntryRouter,
    EntryRouterNode,
    IntentRouter,
    IntentRouterNode,
    LevelGate,
    LevelGateNode,
    PlanPrerequisitesNode,
    ValidatePrerequisitesNode,
)
from graph.schemas import PrerequisiteList
from lessons.models import Lesson, Stage

pytestmark = pytest.mark.django_db

PLANNED = {
    "prerequisites": [
        {"name": "Counting", "why_needed": "Search steps are counted."},
        {"name": "Ordering numbers", "why_needed": "Halving needs a sorted list."},
        {"name": "Lists", "why_needed": "Search runs over a list."},
    ]
}


def assessment(level="beginner", **over):
    base = {
        "level": level, "known_concepts": [], "gaps": [], "prerequisites_to_cover": [], "start_point": "x",
        "author_notes": "y", "confidence": "low", "source": "self_rating",
    }  # fmt: skip
    return LevelScheme.stamp(base | over)


class TestEntryRouter:
    @pytest.mark.parametrize(("state", "destination"), [
        ({"entry": "diagnostic"}, "generate_diagnostic"),
        ({}, "generate_diagnostic"),
        ({"entry": "self_rating"}, "assess_from_source"),
        ({"entry": "followup"}, "assess_from_source"),
        ({"entry": "quiz_result"}, "assess_from_source"),
    ])  # fmt: skip
    def test_the_quick_check_goes_to_the_quiz_and_any_other_entry_to_its_source(self, state, destination):
        assert EntryRouter()(state) == destination

    def test_the_destinations_can_be_set(self):
        assert EntryRouter(diagnostic="a", rated="b")({"entry": "self_rating"}) == "b"


class TestLevelGate:
    @pytest.mark.parametrize(("entry", "level", "listed", "destination"), [
        ("self_rating", "beginner", [], "plan_prerequisites"),
        ("self_rating", "foundation", [], "intent_router"),
        ("self_rating", "proficient", [], "intent_router"),
        ("self_rating", "expert", [], "intent_router"),
        ("self_rating", "beginner", [{"name": "A"}], "intent_router"),  # already has some
        ("diagnostic", "beginner", [], "intent_router"),  # the quiz found them, or found none
        ("followup", "beginner", [], "plan_prerequisites"),
        ("followup", "expert", [], "intent_router"),
        ("quiz_result", "beginner", [], "plan_prerequisites"),
    ])  # fmt: skip
    def test_only_a_beginner_who_took_no_quiz_has_prerequisites_planned(self, entry, level, listed, destination):
        state = {"entry": entry, "assessment": assessment(level), "prerequisites_to_cover": listed}

        assert LevelGate()(state) == destination

    def test_a_thread_from_before_self_rating_is_a_quick_check(self):
        assert LevelGate()({"assessment": assessment("beginner")}) == "intent_router"

    @pytest.mark.parametrize("entry", ["self_rating", "diagnostic"])
    def test_a_lesson_that_asked_for_sheets_has_nothing_planned_even_for_a_beginner(self, entry):
        state = {"entry": entry, "intent": "sheets", "assessment": assessment("beginner"), "prerequisites_to_cover": []}

        assert LevelGate()(state) == "intent_router"

    def test_an_assessment_without_the_scheme_marker_is_read_by_the_old_names(self):
        old = {"level": "beginner"}  # meant Foundation then
        assert LevelGate()({"entry": "self_rating", "assessment": old}) == "intent_router"


class TestIntentRouter:
    def test_a_lesson_goes_on(self):
        assert IntentRouter({"lesson": "plan_lesson"})({"intent": "lesson"}) == "plan_lesson"

    def test_sheets_go_to_the_sheets_writer(self):
        router = IntentRouter({"lesson": "plan_lesson", "sheets": "plan_sheets"})

        assert router({"intent": "sheets"}) == "plan_sheets"

    def test_a_missing_intent_is_a_lesson(self):
        assert IntentRouter({"lesson": "plan_lesson"})({}) == "plan_lesson"

    def test_an_intent_that_is_not_wired_is_refused_with_a_reason(self):
        with pytest.raises(RunFailed, match="sheets"):
            IntentRouter({"lesson": "plan_lesson"})({"intent": "sheets"})  # a graph that does not write sheets


@pytest.mark.parametrize("node", [EntryRouterNode, LevelGateNode, IntentRouterNode])
def test_a_junction_node_changes_nothing(node, lesson_state, runtime):
    assert node()(lesson_state, runtime) == {}


class TestAssessFromSource:
    def start(self, lesson, **fields):
        Lesson.objects.filter(pk=lesson.pk).update(entry="self_rating", self_rating_halves=5, **fields)

    def test_it_turns_the_rating_into_the_assessment_and_records_it_on_the_lesson(self, lesson, lesson_state, runtime):
        self.start(lesson)

        update = AssessFromSourceNode()(lesson_state | {"entry": "self_rating", "self_rating_halves": 5}, runtime)

        assert update["assessment"]["level"] == "foundation" and update["assessment"]["source"] == "self_rating"
        assert (update["route"], update["prerequisites_to_cover"], update["level_source"]) == (
            "lesson",
            [],
            "self_rating",
        )
        stored = Lesson.objects.get(pk=lesson.pk)
        assert stored.assessment == update["assessment"] and stored.level == "foundation"
        assert (stored.level_source, stored.route, stored.prerequisites_to_cover) == ("self_rating", "lesson", [])
        assert stored.stage == Stage.GENERATING_LESSON

    def test_a_failed_lesson_that_retries_goes_back_to_building(self, lesson, lesson_state, runtime):
        self.start(lesson, stage=Stage.FAILED, error="boom")

        AssessFromSourceNode()(lesson_state | {"entry": "self_rating", "self_rating_halves": 2}, runtime)

        stored = Lesson.objects.get(pk=lesson.pk)
        assert (stored.stage, stored.error, stored.level) == (Stage.GENERATING_LESSON, "", "beginner")

    @pytest.mark.parametrize("before", [Stage.PREPARING_DIAGNOSTIC, Stage.FAILED])
    def test_a_lesson_that_asked_for_sheets_moves_to_writing_them_with_no_lesson_route(
        self, lesson, lesson_state, runtime, before
    ):
        self.start(lesson, intent="sheets", stage=before)

        update = AssessFromSourceNode()(
            lesson_state | {"entry": "self_rating", "self_rating_halves": 2, "intent": "sheets"}, runtime
        )

        stored = Lesson.objects.get(pk=lesson.pk)
        assert (stored.stage, stored.route, stored.level, stored.level_source) == (
            Stage.GENERATING_MATERIAL, "", "beginner", "self_rating",
        )  # fmt: skip
        assert "route" not in update and update["prerequisites_to_cover"] == []

    def test_an_entry_with_no_source_is_refused(self, lesson_state, runtime):
        with pytest.raises(KeyError, match="quiz_result"):
            AssessFromSourceNode()(lesson_state | {"entry": "quiz_result"}, runtime)

    @pytest.mark.parametrize(("followup", "level"), [("foundation", "beginner"), ("advanced", "expert")])
    def test_a_followup_gets_its_level_from_what_it_is_for_and_the_test_score_as_the_source(
        self, lesson, lesson_state, runtime, followup, level
    ):
        Lesson.objects.filter(pk=lesson.pk).update(entry="followup", followup_level=followup)

        update = AssessFromSourceNode()(lesson_state | {"entry": "followup", "followup_level": followup}, runtime)

        assert update["assessment"]["level"] == level and update["assessment"]["source"] == "followup"
        assert update["level_source"] == "test_score" and update["route"] == "lesson"
        stored = Lesson.objects.get(pk=lesson.pk)
        assert (stored.level, stored.level_source, stored.route, stored.stage) == (
            level, "test_score", "lesson", Stage.GENERATING_LESSON,
        )  # fmt: skip


class TestPlanPrerequisites:
    def test_it_asks_for_a_list_and_counts_the_attempt(self, lesson_state, gateway, runtime):
        gateway.script("prerequisites.plan", PLANNED)

        update = PlanPrerequisitesNode()(lesson_state | {"assessment": assessment()}, runtime)

        assert update == {"prerequisite_plan": PLANNED, "attempts": {"prerequisites": 1}}
        assert gateway.called("prerequisites.plan")[0].schema is PrerequisiteList

    def test_the_problems_of_the_last_attempt_reach_the_model(self, lesson_state, gateway, runtime):
        gateway.script("prerequisites.plan", PLANNED)
        state = lesson_state | {"assessment": assessment(), "feedback": {"prerequisites": ["List 3 to 6."]}}

        PlanPrerequisitesNode()(state, runtime)

        assert "List 3 to 6." in gateway.called("prerequisites.plan")[0].messages[1].content


class TestValidatePrerequisites:
    def state(self, lesson_state, planned=PLANNED, **over):
        return (
            lesson_state
            | {"assessment": assessment(), "prerequisite_plan": planned, "attempts": {"prerequisites": 1}}
            | over
        )

    def test_a_good_list_becomes_the_lessons_prerequisites(self, lesson, lesson_state, runtime):
        update = ValidatePrerequisitesNode()(self.state(lesson_state), runtime)

        assert update["feedback"] == {"prerequisites": []}
        assert update["prerequisites_to_cover"] == PLANNED["prerequisites"]
        assert update["assessment"]["prerequisites_to_cover"] == ["Counting", "Ordering numbers", "Lists"]
        stored = Lesson.objects.get(pk=lesson.pk)
        assert stored.prerequisites_to_cover == PLANNED["prerequisites"]
        assert stored.assessment["prerequisites_to_cover"] == ["Counting", "Ordering numbers", "Lists"]

    def test_a_bad_list_asks_for_another_attempt_with_the_problems(self, lesson, lesson_state, runtime):
        update = ValidatePrerequisitesNode()(
            self.state(lesson_state, {"prerequisites": PLANNED["prerequisites"][:1]}), runtime
        )

        assert update["feedback"]["prerequisites"] == ["List 3 to 6 prerequisites; there are 1."]
        assert "error" not in update and "prerequisites_to_cover" not in update
        assert Lesson.objects.get(pk=lesson.pk).prerequisites_to_cover == []

    def test_a_list_that_stays_bad_gives_up_and_retries_at_the_planner(self, lesson_state, runtime):
        state = self.state(lesson_state, {"prerequisites": PLANNED["prerequisites"][:1]}, attempts={"prerequisites": 2})

        update = ValidatePrerequisitesNode()(state, runtime)

        assert "The list of prerequisites still failed its checks after 2 attempts" in update["error"]
        assert (update["failed_node"], update["retry_keys"]) == ("plan_prerequisites", ["prerequisites"])

    def test_the_topic_is_not_accepted_as_a_prerequisite(self, lesson_state, runtime):
        planned = {"prerequisites": [{"name": "Binary search", "why_needed": "x"}, *PLANNED["prerequisites"][:2]]}

        update = ValidatePrerequisitesNode()(self.state(lesson_state, planned), runtime)

        assert any("topic itself" in p for p in update["feedback"]["prerequisites"])
