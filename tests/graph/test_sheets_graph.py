"""Unit under test: the sheets writer wired in the compiled graphs (`SheetsSegment` in the lesson flow after
`DiagnoseSegment` and `EntrySegment`, and `StudyMaterialGraphBuilder`, the small graph for a ready lesson).

Why: sheets are asked for in three ways (a lesson that is only sheets, from a topic with a quick check or a rating; a
perfect score's choice; another sheet on a ready lesson) and all must end with the same rows, written by the same
nodes. The wiring decides that a learner who asked for sheets meets no prerequisite quiz and no mastery choice whatever
their score, that a self-rated Beginner has nothing planned for a lesson that will never exist, that the lesson ends
ready with no pages and no route, and that an extra sheet never takes a ready lesson out of ready. These tests run the
real graphs with a scripted gateway and an in-memory checkpointer, as the runner does.

Use cases:
- a quick check lesson that asked for sheets goes from the graded score straight to the assessment and the sheets, at a
  low, a middle and a perfect score: no prerequisite quiz, no mastery choice, no lesson planner
- it ends ready with the sheets it was asked for (both, or just one), no lesson route, the intent kept, and the sheets
  grounded in the quiz's concepts and the level the assessment gave
- a self-rated lesson that asked for sheets meets no quiz, no assessment model call and no prerequisite planning even at
  one star, and its sheets are grounded in the topic and level alone
- a sheet that stays bad fails the run with a reason at the sheets writer, and Retry writes the sheets asked for again
- the small graph writes the kinds asked for on a ready lesson, grounded in the lesson, and the lesson stays ready the
  whole time; it saves a second sheet next to the first
- the small graph on a failing sheet ends with its reason and leaves the lesson ready and nothing saved
- a graph without a sheets writer refuses an intent of sheets with a reason
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from support.driver import GraphDriver
from support.lesson_data import make_pages, make_plan
from support.study_data import CONCEPTS, make_cheat_sheet, make_revision_sheet

from graph.builders import DiagnoseSegment, EntrySegment, StudyMaterialGraphBuilder
from graph.errors import RunFailed
from lessons.models import Lesson, Quiz, Stage, StudyMaterial

pytestmark = pytest.mark.django_db(transaction=True)

ASSESSMENT = {
    "level": "foundation", "known_concepts": ["Halving the range 0"], "gaps": ["Time complexity 1"],
    "prerequisites_to_cover": [], "start_point": "Halving", "author_notes": "Brisk.", "confidence": "medium",
}  # fmt: skip
BOTH = ["cheat_sheet", "revision_sheet"]


def by_kind(messages):
    return make_cheat_sheet() if "CHEAT SHEET" in messages[0].content else make_revision_sheet()


def quiz_bundle(valid_bundle):
    questions = [{**q, "concept": CONCEPTS[n % 2] + f" {n}"} for n, q in enumerate(valid_bundle["diagnostic"])]
    return {**valid_bundle, "diagnostic": questions}


def asked_for_sheets(lesson, **fields):
    Lesson.objects.filter(pk=lesson.pk).update(intent="sheets", **fields)


@pytest.fixture
def run(lesson, ctx, lesson_state):
    return GraphDriver(lesson, ctx, lesson_state)


class TestFromAQuickCheck:
    @pytest.mark.parametrize("right", [0, 5, 10])
    def test_every_score_goes_straight_to_the_assessment_and_the_sheets(
        self, run, gateway, valid_bundle, lesson, right
    ):
        asked_for_sheets(lesson)
        gateway.script("diagnostic.generate", quiz_bundle(valid_bundle))
        gateway.script("learner.assess", ASSESSMENT)
        gateway.respond("study.generate", by_kind)

        run.start(sheet_kinds=BOTH).answer("diagnostic", right=right)

        assert run.interrupt is None
        assert run.nodes[-8:] == [
            "grade_diagnostic", "assess_learner", "level_gate", "intent_router", "plan_sheets", "generate_sheet",
            "generate_sheet", "sheets_join",
        ]  # fmt: skip
        for node in (
            "publish_prerequisite",
            "publish_mastery_options",
            "await_choice",
            "plan_lesson",
            "plan_prerequisites",
        ):
            assert node not in run.nodes
        stored = Lesson.objects.get(pk=lesson.pk)
        assert (stored.stage, stored.route, stored.intent, stored.level) == (Stage.READY, "", "sheets", "foundation")
        assert sorted(StudyMaterial.objects.filter(lesson=lesson).values_list("kind", flat=True)) == BOTH

    def test_the_sheets_rest_on_the_quizs_concepts_and_the_level_found(self, run, gateway, valid_bundle, lesson):
        asked_for_sheets(lesson)
        gateway.script("diagnostic.generate", quiz_bundle(valid_bundle))
        gateway.script("learner.assess", ASSESSMENT)
        gateway.respond("study.generate", by_kind)

        run.start(sheet_kinds=BOTH).answer("diagnostic", right=10)

        for call in gateway.called("study.generate"):
            system, user = (m.content for m in call.messages)
            assert "ALREADY KNOWS" not in system  # even a perfect score is not called an expert here
            assert "foundation" in user and "Halving the range 0" in user and "Time complexity 1" in user

    def test_one_sheet_asked_for_is_the_only_one_written(self, run, gateway, valid_bundle, lesson):
        asked_for_sheets(lesson)
        gateway.script("diagnostic.generate", quiz_bundle(valid_bundle))
        gateway.script("learner.assess", ASSESSMENT)
        gateway.script("study.generate", make_revision_sheet())

        run.start(sheet_kinds=["revision_sheet"]).answer("diagnostic", right=4)

        assert run.nodes.count("generate_sheet") == 1 and len(gateway.called("study.generate")) == 1
        assert list(StudyMaterial.objects.filter(lesson=lesson).values_list("kind", flat=True)) == ["revision_sheet"]
        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.READY

    def test_a_perfect_score_pauses_nowhere(self, run, gateway, valid_bundle, lesson):
        asked_for_sheets(lesson)
        gateway.script("diagnostic.generate", quiz_bundle(valid_bundle))
        gateway.script("learner.assess", ASSESSMENT)
        gateway.respond("study.generate", by_kind)

        run.start(sheet_kinds=BOTH).answer("diagnostic", right=10)

        assert run.interrupt is None  # the choice was made when they asked


class TestFromARating:
    @pytest.mark.parametrize("halves", [1, 5, 10])
    def test_no_quiz_no_assessment_call_and_no_prerequisites_planned_at_any_level(self, run, gateway, lesson, halves):
        asked_for_sheets(lesson, entry="self_rating", self_rating_halves=halves)
        gateway.respond("study.generate", by_kind)

        run.start(sheet_kinds=BOTH)

        assert run.interrupt is None
        assert run.nodes[:3] == ["load_context", "entry_router", "assess_from_source"]
        for node in ("generate_diagnostic", "assess_learner", "plan_prerequisites", "plan_lesson"):
            assert node not in run.nodes
        assert not gateway.called("prerequisites.plan") and not gateway.called("diagnostic.generate")
        stored = Lesson.objects.get(pk=lesson.pk)
        assert (stored.stage, stored.route, stored.level_source) == (Stage.READY, "", "self_rating")
        assert (
            not Quiz.objects.filter(lesson=lesson).exists() and StudyMaterial.objects.filter(lesson=lesson).count() == 2
        )

    def test_the_sheets_rest_on_the_topic_and_the_level_alone(self, run, gateway, lesson):
        asked_for_sheets(lesson, entry="self_rating", self_rating_halves=10)
        gateway.respond("study.generate", by_kind)

        run.start(sheet_kinds=BOTH)

        for call in gateway.called("study.generate"):
            user = call.messages[1].content
            assert "expert" in user.lower() and "Key concepts that must be covered" not in user


class TestWhenASheetStaysBad:
    def test_the_run_fails_at_the_writer_and_retry_writes_them_again(self, run, gateway, lesson):
        asked_for_sheets(lesson, entry="self_rating", self_rating_halves=5)
        thin = make_revision_sheet()
        thin["subtopics"] = thin["subtopics"][:2]
        writes = {"revision": 0}

        def write(messages):
            if "CHEAT SHEET" in messages[0].content:
                return make_cheat_sheet()
            writes["revision"] += 1
            return thin if writes["revision"] <= 2 else make_revision_sheet()

        gateway.respond("study.generate", write)

        run.start(sheet_kinds=BOTH)

        assert run.interrupt["kind"] == "retry"
        stored = Lesson.objects.get(pk=lesson.pk)
        assert stored.stage == Stage.FAILED and "still failed their checks" in stored.error
        assert not StudyMaterial.objects.filter(lesson=lesson).exists()

        run.stream(Command(resume=True))

        assert run.interrupt is None and run.nodes.count("plan_sheets") == 2
        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.READY and StudyMaterial.objects.count() == 2


def plan_about_the_sheets():
    """A plan whose concepts are the ones the canned sheets talk about."""
    plan = make_plan()
    for page in plan["pages"]:
        for n, item in enumerate(page["outline"]):
            item["concept"] = item["heading"] = CONCEPTS[n % 2]
    return plan


@pytest.fixture
def ready_lesson(lesson):
    plan = plan_about_the_sheets()
    Lesson.objects.filter(pk=lesson.pk).update(
        stage=Stage.READY, title=plan["title"], level="proficient", plan=plan, pages=make_pages(plan), route="lesson"
    )
    return Lesson.objects.get(pk=lesson.pk)


class TestAnExtraSheet:
    def build(self, ctx):
        return StudyMaterialGraphBuilder().build(InMemorySaver())

    def invoke(self, graph, ctx, lesson, kinds, thread="t1"):
        stages = []
        config = {"configurable": {"thread_id": thread}}
        payload = {"lesson_id": str(lesson.id), "sheet_kinds": kinds, "extra_material": True}
        for _ in graph.stream(payload, config, context=ctx, stream_mode=["updates"]):
            stages.append(Lesson.objects.get(pk=lesson.pk).stage)
        return stages

    def test_it_writes_the_kinds_asked_for_grounded_in_the_lesson_and_the_lesson_stays_ready(
        self, ready_lesson, ctx, gateway
    ):
        gateway.respond("study.generate", by_kind)

        stages = self.invoke(self.build(ctx), ctx, ready_lesson, BOTH)

        assert set(stages) == {Stage.READY}
        assert sorted(StudyMaterial.objects.filter(lesson=ready_lesson).values_list("kind", flat=True)) == BOTH
        for call in gateway.called("study.generate"):
            assert (
                "just studied" in call.messages[0].content
                and plan_about_the_sheets()["summary"] in call.messages[1].content
            )

    def test_a_second_sheet_is_saved_next_to_the_first(self, ready_lesson, ctx, gateway):
        graph = self.build(ctx)
        gateway.respond("study.generate", by_kind)

        self.invoke(graph, ctx, ready_lesson, ["cheat_sheet"], "t1")
        self.invoke(graph, ctx, ready_lesson, ["revision_sheet"], "t2")

        assert sorted(StudyMaterial.objects.filter(lesson=ready_lesson).values_list("kind", flat=True)) == BOTH
        assert len(gateway.called("study.generate")) == 2

    def test_a_sheet_that_stays_bad_ends_the_run_with_its_reason_and_leaves_the_lesson_ready(
        self, ready_lesson, ctx, gateway
    ):
        thin = make_cheat_sheet()
        thin["sections"] = thin["sections"][:1]
        gateway.respond("study.generate", lambda messages: thin)

        with pytest.raises(RunFailed, match="still failed their checks"):
            self.invoke(self.build(ctx), ctx, ready_lesson, ["cheat_sheet"])

        assert not StudyMaterial.objects.filter(lesson=ready_lesson).exists()
        assert Lesson.objects.get(pk=ready_lesson.pk).stage == Stage.READY


def test_a_graph_without_a_sheets_writer_refuses_an_intent_of_sheets_with_a_reason(lesson, ctx, lesson_state, gateway):
    asked_for_sheets(lesson, entry="self_rating", self_rating_halves=5)
    run = GraphDriver(lesson, ctx, lesson_state, [DiagnoseSegment(), EntrySegment()])

    with pytest.raises(RunFailed, match="sheets"):
        run.start(sheet_kinds=BOTH)
