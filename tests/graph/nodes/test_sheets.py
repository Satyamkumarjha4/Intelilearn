"""Unit under test: the mastery choice's own steps (`graph.nodes.sheets`): `ChoiceRouter`, `plan_sheets`,
`generate_sheet`, `sheets_join` and their routers, with `graph.sheets.SheetWriter` and `SheetKinds`.

Why: a learner who aced the quiz picks the Expert lesson or two sheets. The sheets are written at once, so the node that
joins them must save both or neither, send back only the one that failed its rules, and give up with a reason when a
sheet runs out of attempts. A router that sends the wrong choice to the wrong place gives the learner something they
did not pick; a join that saved one sheet and failed on the other would leave a ready lesson with half of what it
promised.

Use cases:
- the choice router sends the Expert lesson to the assessment, the sheets to the planner, and a sheet kind from before
  the two-way choice to the single-sheet writer
- plan_sheets moves the lesson to writing, reads the quiz's concepts, and clears the sheets, problems and attempts so a
  Retry starts both sheets again; the plan router then sends one branch for each sheet, with the concepts
- generate_sheet writes one sheet of its kind, keeps it (with its problems) and counts the attempt for that sheet only
- generate_sheet is held to the rules of the single-sheet path: a sheet that lacks the concepts has problems, and the
  problems of the last attempt reach the model
- sheets_join saves both sheets and marks the lesson ready when both pass, and says so
- sheets_join sends back only the sheet that failed while it has attempts left, and says so
- sheets_join gives up when a sheet is out of attempts: a readable error, a retry at plan_sheets, both sheets' counters
  reset, and nothing saved
- the sheets router finishes, retries only the failed sheet, or leaves for the failure node
"""

import pytest
from langgraph.graph import END
from support.quiz_data import make_questions
from support.study_data import CONCEPTS, make_cheat_sheet, make_revision_sheet

from graph.nodes.sheets import (
    ChoiceRouter,
    GenerateSheetNode,
    PlanSheetsNode,
    PlanSheetsRouter,
    SheetsJoinNode,
    SheetsRouter,
    SheetStatus,
)
from graph.schemas import CheatSheet, RevisionSheet
from lessons.models import Lesson, Stage, StudyMaterial

pytestmark = pytest.mark.django_db

WRITTEN = {"cheat_sheet": make_cheat_sheet(), "revision_sheet": make_revision_sheet()}


def quiz_state(lesson_state, **extra):
    questions = [{**q, "concept": CONCEPTS[n % 2]} for n, q in enumerate(make_questions())]
    return lesson_state | {"bundle": {"diagnostic": questions}} | extra


def branch(state, kind, feedback=()):
    """What a `Send` hands the branch: the shared context, the sheet to write and the problems to fix."""
    return state | {"key": kind, "feedback": list(feedback), "concepts": CONCEPTS}


class TestChoiceRouter:
    router = ChoiceRouter(lesson="assess_learner", sheets="plan_sheets", legacy="generate_study_material")

    @pytest.mark.parametrize(("choice", "destination"), [
        ("lesson", "assess_learner"), ("sheets", "plan_sheets"), ("cheat_sheet", "generate_study_material"),
        ("revision_sheet", "generate_study_material"), ("practice_sheet", "generate_study_material"),
    ])  # fmt: skip
    def test_each_choice_goes_where_it_belongs(self, choice, destination):
        assert self.router({"mastery_choice": choice}) == destination


class TestPlanSheets:
    def test_it_moves_the_lesson_to_writing_and_reads_the_concepts(self, lesson, lesson_state, runtime):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.AWAITING_CHOICE)

        update = PlanSheetsNode()(quiz_state(lesson_state), runtime)

        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.GENERATING_MATERIAL
        assert update["concepts"] == [q["concept"] for q in quiz_state(lesson_state)["bundle"]["diagnostic"]]

    def test_it_clears_the_sheets_the_problems_and_the_attempts_for_a_fresh_start(self, lesson, lesson_state, runtime):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.AWAITING_CHOICE)

        update = PlanSheetsNode()(quiz_state(lesson_state), runtime)

        keys = {"sheet:cheat_sheet": None, "sheet:revision_sheet": None}
        assert update["sheets"] == {"cheat_sheet": None, "revision_sheet": None}
        assert update["feedback"] == keys and update["attempts"] == keys

    def test_the_router_sends_one_branch_for_each_sheet_with_the_concepts(self, lesson_state):
        sends = PlanSheetsRouter()(lesson_state | {"concepts": CONCEPTS})

        assert [s.node for s in sends] == ["generate_sheet", "generate_sheet"]
        assert [s.arg["key"] for s in sends] == ["cheat_sheet", "revision_sheet"]
        assert all(s.arg["concepts"] == CONCEPTS and s.arg["topic"] == "Binary search" for s in sends)


class TestGenerateSheet:
    @pytest.mark.parametrize(("kind", "schema"), [("cheat_sheet", CheatSheet), ("revision_sheet", RevisionSheet)])
    def test_it_writes_one_sheet_of_its_kind_and_counts_that_sheets_attempt(
        self, lesson_state, gateway, runtime, kind, schema
    ):
        gateway.script("study.generate", WRITTEN[kind])

        update = GenerateSheetNode()(branch(lesson_state, kind), runtime)

        key = f"sheet:{kind}"
        assert update == {"sheets": {kind: WRITTEN[kind]}, "feedback": {key: []}, "attempts": {key: 1}}
        call = gateway.called("study.generate")[0]
        assert call.schema is schema and "Key concepts that must be covered" in call.messages[1].content

    def test_a_sheet_that_lacks_the_concepts_has_problems_and_is_still_kept(self, lesson_state, gateway, runtime):
        gateway.script("study.generate", WRITTEN["cheat_sheet"])
        state = branch(lesson_state, "cheat_sheet") | {"concepts": ["Quantum tunnelling", "Dark energy", "Entropy"]}

        update = GenerateSheetNode()(state, runtime)

        assert update["sheets"] == {"cheat_sheet": WRITTEN["cheat_sheet"]}
        assert any("key concepts" in p for p in update["feedback"]["sheet:cheat_sheet"])

    def test_the_problems_of_the_last_attempt_reach_the_model(self, lesson_state, gateway, runtime):
        gateway.script("study.generate", WRITTEN["cheat_sheet"])
        state = branch(lesson_state, "cheat_sheet", ["Use at least 2 sections."])

        GenerateSheetNode()(state, runtime)

        assert "Use at least 2 sections." in gateway.called("study.generate")[0].messages[1].content


def joined(lesson_state, *, cheat=(), revision=(), attempts=(1, 1), sheets=WRITTEN):
    return lesson_state | {
        "sheets": dict(sheets),
        "feedback": {"sheet:cheat_sheet": list(cheat), "sheet:revision_sheet": list(revision)},
        "attempts": {"sheet:cheat_sheet": attempts[0], "sheet:revision_sheet": attempts[1]},
    }


class TestSheetsJoin:
    def test_both_sheets_passing_are_saved_and_the_lesson_is_ready(self, lesson, lesson_state, runtime):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.GENERATING_MATERIAL, route="mastery")

        update = SheetsJoinNode()(joined(lesson_state), runtime)

        assert update == {"sheets_outcome": "complete"}
        saved = {m.kind: m.content for m in StudyMaterial.objects.filter(lesson=lesson)}
        assert saved == WRITTEN and Lesson.objects.get(pk=lesson.pk).stage == Stage.READY
        assert Lesson.objects.get(pk=lesson.pk).route == "mastery"

    def test_only_the_sheet_that_failed_is_sent_back_while_it_has_attempts_left(self, lesson, lesson_state, runtime):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.GENERATING_MATERIAL)

        update = SheetsJoinNode()(joined(lesson_state, revision=["Cover every subtopic."]), runtime)

        assert update == {"sheets_outcome": "retry"}
        assert StudyMaterial.objects.filter(lesson=lesson).count() == 0
        assert SheetStatus.of(joined(lesson_state, revision=["x"])) == (["revision_sheet"], [])

    def test_a_sheet_out_of_attempts_fails_the_run_with_a_reason_and_saves_nothing(self, lesson, lesson_state, runtime):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.GENERATING_MATERIAL)

        update = SheetsJoinNode()(joined(lesson_state, cheat=["Use at least 2 sections."], attempts=(2, 1)), runtime)

        assert update["sheets_outcome"] == "failed"
        assert "still failed their checks: Use at least 2 sections." in update["error"]
        assert update["failed_node"] == "plan_sheets"
        assert update["retry_keys"] == ["sheet:cheat_sheet", "sheet:revision_sheet"]
        assert StudyMaterial.objects.filter(lesson=lesson).count() == 0
        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.GENERATING_MATERIAL

    def test_a_retry_is_announced(self, lesson_state, runtime, events):
        SheetsJoinNode()(joined(lesson_state, revision=["Cover every subtopic."]), runtime)

        attempt = next(e for e in events.events if e.get("type") == "attempt")
        assert (attempt["node"], attempt["attempt"], attempt["reason"]) == (
            "generate_sheet",
            2,
            "Cover every subtopic.",
        )


class TestSheetsRouter:
    def test_a_finished_pair_ends_the_flow(self, lesson_state):
        assert SheetsRouter()(lesson_state | {"sheets_outcome": "complete"}) == END

    def test_a_failure_leaves_for_the_failure_node(self, lesson_state):
        assert SheetsRouter(on_fail="mark_failed")(lesson_state | {"sheets_outcome": "failed"}) == "mark_failed"

    def test_a_retry_sends_back_only_the_failed_sheet_with_its_problems(self, lesson_state):
        state = joined(lesson_state, revision=["Cover every subtopic."])
        state |= {"sheets_outcome": "retry", "concepts": CONCEPTS}

        (send,) = SheetsRouter()(state)

        assert send.node == "generate_sheet" and send.arg["key"] == "revision_sheet"
        assert send.arg["feedback"] == ["Cover every subtopic."]
