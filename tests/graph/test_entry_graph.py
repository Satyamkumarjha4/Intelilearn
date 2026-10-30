"""Unit under test: the ways into a lesson and the mastery choice, wired in the compiled flow graph
(`graph.builders.EntrySegment`, `MasterySegment`, `SheetsSegment` after `DiagnoseSegment`).

Why: the nodes pass their own tests, but the wiring decides that a self-rated learner meets no quiz and no quiz model
call, that only a Beginner gets prerequisites planned, that the learner who aced the quiz gets exactly the option they
picked, that the two sheets are written together and one that fails is the only one written again, and that a lesson
already waiting at the old choice still resumes. These tests run the real graph with a scripted gateway and an
in-memory checkpointer, and resume it with `Command(resume=…)` as the runner does. The lesson stage (Stage B on) is
stood in for by a node that records what the planner would receive.

Use cases:
- a self-rated learner at each of the four levels reaches the lesson planner with no quiz, no quiz model call, the
  level of the stars, the lesson route and the self-rating as the level source
- only a Beginner has prerequisites planned: the model is asked, the list is checked, saved on the lesson, and handed to
  the planner; the other three levels are not asked
- a prerequisite list that fails its rules is planned again with the problems, and one that stays bad fails the run
  with a reason, and Retry plans it again from fresh counters
- a lesson made from a test result needs no quiz and no rating: a Foundation follow-up is a Beginner lesson whose
  prerequisites are planned as usual, an Advanced follow-up an Expert lesson with none, and both record the test score
  as where the level came from
- a quick check that ends in Beginner is not asked for prerequisites (the quiz found them) and still reaches the planner
- a thread checkpointed before self-rating (no entry in its state) is a quick check
- a perfect score pauses at the choice; the Expert lesson sets the level to Expert whatever the model said, makes the
  route the lesson route, and goes on to the planner
- the sheets choice writes the cheat sheet and the revision sheet in parallel from the quiz's concepts, saves both,
  makes the lesson ready, keeps the mastery route and asks for no assessment
- a sheet that fails its rules is written again alone; a sheet that stays bad fails the run and Retry writes both again
- a lesson already waiting at the old choice still resumes with one sheet kind, in both the old and the new form
"""

import pytest
from langgraph.graph import StateGraph
from langgraph.types import Command
from support.driver import GraphDriver
from support.study_data import CONCEPTS, make_cheat_sheet, make_revision_sheet

from graph.builder_base import Segment
from graph.builders import DiagnoseSegment, EntrySegment, MasterySegment, SheetsSegment
from lessons.models import Lesson, Quiz, Stage, StudyMaterial

pytestmark = pytest.mark.django_db(transaction=True)

PLANNED = {
    "prerequisites": [
        {"name": "Counting", "why_needed": "Search steps are counted."},
        {"name": "Ordering numbers", "why_needed": "Halving needs a sorted list."},
        {"name": "Lists", "why_needed": "Search runs over a list."},
    ]
}
#: passes the schema (three items) and breaks a rule (a name repeated), which only the validator catches
REPEATED = {"prerequisites": [PLANNED["prerequisites"][0], PLANNED["prerequisites"][0], PLANNED["prerequisites"][1]]}
MODEL_ASSESSMENT = {
    "level": "foundation", "known_concepts": ["a"], "gaps": ["b"], "prerequisites_to_cover": ["made up"],
    "start_point": "Halving", "author_notes": "Brisk.", "confidence": "medium",
}  # fmt: skip
SEEN: list[dict] = []


class RecordPlanner:
    """Stands in for Stage B: the node the `lesson` exit leads to, remembering what the planner would be handed."""

    name = "plan_lesson"

    def __call__(self, state, runtime):
        SEEN.append({k: state.get(k) for k in ("assessment", "prerequisites_to_cover", "route", "entry")})
        return {}


class PlannerStub(Segment):
    provides = {"lesson": "plan_lesson"}

    def add_nodes(self, graph: StateGraph) -> None:
        graph.add_node("plan_lesson", RecordPlanner())

    def add_edges(self, graph, exits) -> None:
        graph.add_edge("plan_lesson", "__end__")


@pytest.fixture(autouse=True)
def forget():
    SEEN.clear()


def drive(lesson, ctx, lesson_state):
    return GraphDriver(
        lesson, ctx, lesson_state, [DiagnoseSegment(), EntrySegment(), MasterySegment(), SheetsSegment(), PlannerStub()]
    )


def rate(lesson, halves):
    Lesson.objects.filter(pk=lesson.pk).update(entry="self_rating", self_rating_halves=halves)


@pytest.fixture
def run(lesson, ctx, lesson_state):
    return drive(lesson, ctx, lesson_state)


def by_kind(messages):
    """The sheet the prompt asks for."""
    return make_cheat_sheet() if "CHEAT SHEET" in messages[0].content else make_revision_sheet()


def mastery_bundle(valid_bundle):
    questions = [{**q, "concept": CONCEPTS[n % 2] + f" {n}"} for n, q in enumerate(valid_bundle["diagnostic"])]
    return {**valid_bundle, "diagnostic": questions}


class TestSelfRated:
    @pytest.mark.parametrize(("halves", "level", "beginner"), [
        (1, "beginner", True), (3, "beginner", True), (4, "foundation", False), (7, "foundation", False),
        (8, "proficient", False), (9, "expert", False), (10, "expert", False),
    ])  # fmt: skip
    def test_each_half_star_reaches_the_planner_at_its_level_with_no_quiz(
        self, run, gateway, lesson, halves, level, beginner
    ):
        rate(lesson, halves)
        gateway.script("prerequisites.plan", PLANNED)

        run.start()

        assert run.interrupt is None
        assert run.nodes[:3] == ["load_context", "entry_router", "assess_from_source"]
        for node in ("generate_diagnostic", "await_diagnostic", "assess_learner"):
            assert node not in run.nodes
        assert not gateway.called("diagnostic.generate") and not gateway.called("learner.assess")
        assert run.nodes[-2:] == ["intent_router", "plan_lesson"]
        stored = Lesson.objects.get(pk=lesson.pk)
        assert (stored.level, stored.level_source, stored.route) == (level, "self_rating", "lesson")
        assert stored.stage == Stage.GENERATING_LESSON and not Quiz.objects.filter(lesson=lesson).exists()
        assert SEEN[0]["assessment"]["source"] == "self_rating" and SEEN[0]["entry"] == "self_rating"
        assert ("plan_prerequisites" in run.nodes) is beginner
        assert len(gateway.called("prerequisites.plan")) == (1 if beginner else 0)

    def test_a_beginners_prerequisites_are_checked_saved_and_handed_to_the_planner(self, run, gateway, lesson):
        rate(lesson, 2)
        gateway.script("prerequisites.plan", PLANNED)

        run.start()

        assert run.nodes[3:7] == ["level_gate", "plan_prerequisites", "validate_prerequisites", "intent_router"]
        names = ["Counting", "Ordering numbers", "Lists"]
        stored = Lesson.objects.get(pk=lesson.pk)
        assert [p["name"] for p in stored.prerequisites_to_cover] == names
        assert stored.assessment["prerequisites_to_cover"] == names
        assert [p["name"] for p in SEEN[0]["prerequisites_to_cover"]] == names
        assert SEEN[0]["assessment"]["prerequisites_to_cover"] == names

    def test_a_list_that_fails_its_rules_is_planned_again_with_the_problems(self, run, gateway, lesson):
        rate(lesson, 2)
        gateway.script("prerequisites.plan", REPEATED, PLANNED)

        run.start()

        assert run.nodes.count("plan_prerequisites") == 2
        assert "Prerequisites must be different" in gateway.called("prerequisites.plan")[1].messages[1].content
        assert run.nodes[-1] == "plan_lesson" and len(SEEN[0]["prerequisites_to_cover"]) == 3

    def test_a_list_that_stays_bad_fails_the_run_and_retry_plans_it_again_from_fresh_counters(
        self, run, gateway, lesson
    ):
        rate(lesson, 2)
        gateway.script("prerequisites.plan", REPEATED, REPEATED, PLANNED)

        run.start()

        assert run.interrupt["kind"] == "retry" and run.nodes[-1] == "mark_failed"
        stored = Lesson.objects.get(pk=lesson.pk)
        assert stored.stage == Stage.FAILED and "The list of prerequisites still failed" in stored.error

        run.stream(Command(resume=True))

        assert run.nodes.count("plan_prerequisites") == 3 and run.nodes[-1] == "plan_lesson"
        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.GENERATING_LESSON

    def test_a_thread_from_before_self_rating_is_a_quick_check(self, run, gateway, valid_bundle, lesson):
        gateway.script("diagnostic.generate", valid_bundle)
        # a checkpointed state had no `entry`: the first node of the new graph still asks the lesson, which defaults
        # to a quick check, so the quiz is built
        run.start()

        assert run.interrupt["kind"] == "diagnostic"
        assert run.nodes[:3] == ["load_context", "entry_router", "generate_diagnostic"]


class TestFollowup:
    def made_from(self, lesson, level):
        Lesson.objects.filter(pk=lesson.pk).update(entry="followup", followup_level=level, origin="followup")

    def test_a_foundation_followup_is_a_beginner_lesson_with_its_prerequisites_planned(self, run, gateway, lesson):
        self.made_from(lesson, "foundation")
        gateway.script("prerequisites.plan", PLANNED)

        run.start()

        assert run.interrupt is None and run.nodes[:3] == ["load_context", "entry_router", "assess_from_source"]
        assert "plan_prerequisites" in run.nodes and run.nodes[-1] == "plan_lesson"
        stored = Lesson.objects.get(pk=lesson.pk)
        assert (stored.level, stored.level_source, stored.route) == ("beginner", "test_score", "lesson")
        assert len(stored.prerequisites_to_cover) == 3 and SEEN[0]["entry"] == "followup"
        assert not gateway.called("diagnostic.generate") and not gateway.called("learner.assess")

    def test_an_advanced_followup_is_an_expert_lesson_with_no_prerequisites(self, run, gateway, lesson):
        self.made_from(lesson, "advanced")

        run.start()

        assert "plan_prerequisites" not in run.nodes and not gateway.called("prerequisites.plan")
        stored = Lesson.objects.get(pk=lesson.pk)
        assert (stored.level, stored.level_source, stored.prerequisites_to_cover) == ("expert", "test_score", [])
        assert SEEN[0]["assessment"]["source"] == "followup"


class TestQuickCheck:
    def test_a_beginner_the_quiz_found_is_not_asked_for_prerequisites(self, run, gateway, valid_bundle, lesson):
        gateway.script("diagnostic.generate", valid_bundle)
        gateway.script("learner.assess", MODEL_ASSESSMENT | {"level": "beginner"})

        run.start().answer("diagnostic", right=5)

        assert run.nodes[-4:] == ["assess_learner", "level_gate", "intent_router", "plan_lesson"]
        assert not gateway.called("prerequisites.plan")
        assert SEEN[0]["assessment"]["source"] == "diagnostic" and SEEN[0]["entry"] == "diagnostic"
        assert Lesson.objects.get(pk=lesson.pk).level_source == "diagnostic"


class TestMasteryChoice:
    def perfect(self, run, gateway, valid_bundle):
        gateway.script("diagnostic.generate", mastery_bundle(valid_bundle))
        return run.start().answer("diagnostic", right=10)

    def test_the_perfect_score_pauses_at_the_choice(self, run, gateway, valid_bundle, lesson):
        self.perfect(run, gateway, valid_bundle)

        assert run.interrupt == {"kind": "mastery_choice"}
        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.AWAITING_CHOICE

    def test_the_expert_lesson_sets_the_level_and_the_lesson_route_and_goes_on(
        self, run, gateway, valid_bundle, lesson
    ):
        self.perfect(run, gateway, valid_bundle)
        gateway.script("learner.assess", MODEL_ASSESSMENT)  # the model says foundation: the choice makes it Expert

        run.stream(Command(resume={"choice": "lesson"}))

        assert run.nodes[-4:] == ["assess_learner", "level_gate", "intent_router", "plan_lesson"]
        stored = Lesson.objects.get(pk=lesson.pk)
        assert (stored.level, stored.route, stored.stage) == ("expert", "lesson", Stage.GENERATING_LESSON)
        assert stored.level_source == "diagnostic" and stored.assessment["level"] == "expert"
        assert SEEN[0]["route"] == "lesson" and SEEN[0]["assessment"]["gaps"] == ["b"]
        assert not gateway.called("study.generate") and not gateway.called("prerequisites.plan")

    def test_the_sheets_choice_writes_both_sheets_in_parallel_and_the_lesson_is_ready(
        self, run, gateway, valid_bundle, lesson
    ):
        self.perfect(run, gateway, valid_bundle)
        gateway.respond("study.generate", by_kind)  # the two sheets are asked for in no fixed order

        run.stream(Command(resume={"choice": "sheets"}))

        assert run.interrupt is None
        assert run.nodes[-5:] == ["await_choice", "plan_sheets", "generate_sheet", "generate_sheet", "sheets_join"]
        assert "assess_learner" not in run.nodes and not gateway.called("learner.assess")
        stored = Lesson.objects.get(pk=lesson.pk)
        assert (stored.stage, stored.route) == (Stage.READY, "mastery")
        assert sorted(StudyMaterial.objects.filter(lesson=lesson).values_list("kind", flat=True)) == [
            "cheat_sheet", "revision_sheet"]  # fmt: skip
        kinds = {c.messages[1].content for c in gateway.called("study.generate")}
        assert all("Key concepts that must be covered" in text for text in kinds)

    def test_a_sheet_that_fails_its_rules_is_written_again_alone(self, run, gateway, valid_bundle, lesson):
        self.perfect(run, gateway, valid_bundle)
        thin = make_revision_sheet()
        thin["subtopics"] = thin["subtopics"][:2]

        def write(messages):
            cheat = "CHEAT SHEET" in messages[0].content
            if cheat:
                return make_cheat_sheet()
            return thin if "REJECTED" not in messages[1].content else make_revision_sheet()

        gateway.respond("study.generate", write)

        run.stream(Command(resume={"choice": "sheets"}))

        calls = gateway.called("study.generate")
        assert [("CHEAT SHEET" in c.messages[0].content) for c in calls].count(True) == 1
        assert len(calls) == 3 and "at least 4 are needed" in calls[2].messages[1].content
        assert run.nodes.count("sheets_join") == 2
        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.READY

    def test_a_sheet_that_stays_bad_fails_the_run_and_retry_writes_both_again(self, run, gateway, valid_bundle, lesson):
        self.perfect(run, gateway, valid_bundle)
        thin = make_revision_sheet()
        thin["subtopics"] = thin["subtopics"][:2]
        writes = {"count": 0}

        def write(messages):
            if "CHEAT SHEET" in messages[0].content:
                return make_cheat_sheet()
            writes["count"] += 1
            return thin if writes["count"] <= 2 else make_revision_sheet()

        gateway.respond("study.generate", write)

        run.stream(Command(resume={"choice": "sheets"}))

        assert run.interrupt["kind"] == "retry"
        stored = Lesson.objects.get(pk=lesson.pk)
        assert stored.stage == Stage.FAILED and "still failed their checks" in stored.error
        assert not StudyMaterial.objects.filter(lesson=lesson).exists()

        run.stream(Command(resume=True))

        assert run.interrupt is None and Lesson.objects.get(pk=lesson.pk).stage == Stage.READY
        assert run.nodes.count("plan_sheets") == 2
        assert StudyMaterial.objects.filter(lesson=lesson).count() == 2

    @pytest.mark.parametrize("resume", ["cheat_sheet", {"choice": "cheat_sheet"}])
    def test_a_lesson_already_waiting_at_the_old_choice_still_resumes_with_one_sheet(
        self, run, gateway, valid_bundle, lesson, resume
    ):
        self.perfect(run, gateway, valid_bundle)
        gateway.script("study.generate", make_cheat_sheet())

        run.stream(Command(resume=resume))

        assert run.nodes[-3:] == ["generate_study_material", "validate_study_material", "persist_study_material"]
        assert StudyMaterial.objects.get(lesson=lesson).kind == "cheat_sheet"
        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.READY
