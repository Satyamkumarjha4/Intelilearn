"""Unit under test: the mastery nodes in `graph.nodes.mastery`: offering the sheet choice, writing and validating the
chosen study sheet, and saving it.

Why: a learner who aced the diagnostic gets only this. A node that forgets the stage change leaves the browser on the
wrong screen; one that saves an unchecked sheet shows them a broken template; one that lets an extra sheet change the
stage of a lesson that is already ready would hide the sheets they have.

Use cases:
- publish_mastery_options moves the lesson to awaiting_choice and has no other effect
- await_choice accepts the three sheet kinds and refuses anything else
- generate_study_material asks for the chosen kind's schema, passes the diagnostic's concepts and counts the attempt
- generate_study_material takes the concepts from the stored quiz when the state has no bundle (an extra sheet later)
- generate_study_material moves the lesson to generating_material, except for an extra sheet on a ready lesson
- validate_study_material accepts a good sheet, asks for another attempt with the problems, and gives up with a readable
  error naming the sheet when attempts run out
- persist_study_material saves the sheet once per kind and marks the lesson ready
- the extra-sheet failure node raises a readable error so the run fails without failing the lesson
"""

import pytest
from support.quiz_data import make_questions
from support.study_data import CONCEPTS, make_cheat_sheet, make_practice_sheet, make_revision_sheet

from graph.errors import RunFailed
from graph.nodes.mastery import (
    AwaitChoiceNode,
    FailStudyMaterialNode,
    GenerateStudyMaterialNode,
    PersistStudyMaterialNode,
    PublishMasteryOptionsNode,
    ValidateStudyMaterialNode,
)
from graph.schemas import CheatSheet, PracticeSheet, RevisionSheet
from lessons.models import Lesson, Quiz, Stage, StudyMaterial

SHEETS = {
    "cheat_sheet": (CheatSheet, make_cheat_sheet),
    "revision_sheet": (RevisionSheet, make_revision_sheet),
    "practice_sheet": (PracticeSheet, make_practice_sheet),
}


def quiz_questions():
    """The diagnostic's questions, whose concepts are the ones the sample sheets cover."""
    return [{**q, "concept": CONCEPTS[n % 2]} for n, q in enumerate(make_questions())]


def with_choice(lesson_state, kind, **extra):
    return lesson_state | {"mastery_choice": kind, "bundle": {"diagnostic": quiz_questions()}} | extra


def test_publishing_the_options_moves_the_lesson_to_awaiting_choice(lesson, lesson_state, runtime):
    Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.AWAITING_DIAGNOSTIC)

    update = PublishMasteryOptionsNode()(lesson_state, runtime)

    assert update == {}
    assert Lesson.objects.get(pk=lesson.pk).stage == Stage.AWAITING_CHOICE


class TestAwaitChoice:
    @pytest.mark.parametrize("kind", ["cheat_sheet", "revision_sheet", "practice_sheet"])
    def test_accepts_the_three_kinds(self, kind):
        assert AwaitChoiceNode().accept(kind) == kind

    @pytest.mark.parametrize("value", ["poster", "", None, 3, ["cheat_sheet"]])
    def test_refuses_anything_else(self, value):
        with pytest.raises(ValueError, match="Unknown study sheet"):
            AwaitChoiceNode().accept(value)

    def test_waits_with_its_own_kind_of_interrupt(self):
        assert (AwaitChoiceNode.kind, AwaitChoiceNode.result_key) == ("mastery_choice", "mastery_choice")


class TestGenerate:
    @pytest.mark.parametrize("kind", SHEETS)
    def test_asks_for_the_schema_of_the_chosen_kind_and_counts_the_attempt(
        self, lesson, lesson_state, gateway, runtime, kind
    ):
        schema, make = SHEETS[kind]
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.AWAITING_CHOICE)
        gateway.script("study.generate", make())

        update = GenerateStudyMaterialNode()(with_choice(lesson_state, kind), runtime)

        assert update == {"study_material": make(), "attempts": {"material": 1}}
        assert gateway.called("study.generate")[0].schema is schema

    def test_gives_the_model_the_diagnostic_concepts_and_the_feedback(self, lesson, lesson_state, gateway, runtime):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.AWAITING_CHOICE)
        gateway.script("study.generate", make_cheat_sheet())
        state = with_choice(lesson_state, "cheat_sheet", feedback={"material": ["Use 6 items."]})

        GenerateStudyMaterialNode()(state, runtime)

        user = gateway.called("study.generate")[0].messages[1].content
        assert "Halving the range" in user and "- Use 6 items." in user

    def test_reads_the_concepts_from_the_stored_quiz_without_a_bundle(self, lesson, lesson_state, gateway, runtime):
        Quiz.objects.create(lesson=lesson, kind="diagnostic", questions=quiz_questions())
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.READY)
        gateway.script("study.generate", make_cheat_sheet())

        GenerateStudyMaterialNode()(lesson_state | {"mastery_choice": "cheat_sheet", "extra_material": True}, runtime)

        assert "Time complexity" in gateway.called("study.generate")[0].messages[1].content

    def test_moves_the_lesson_to_generating_material(self, lesson, lesson_state, gateway, runtime):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.AWAITING_CHOICE)
        gateway.script("study.generate", make_cheat_sheet())

        GenerateStudyMaterialNode()(with_choice(lesson_state, "cheat_sheet"), runtime)

        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.GENERATING_MATERIAL

    def test_an_extra_sheet_leaves_a_ready_lesson_ready(self, lesson, lesson_state, gateway, runtime):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.READY)
        gateway.script("study.generate", make_cheat_sheet())

        GenerateStudyMaterialNode()(with_choice(lesson_state, "cheat_sheet", extra_material=True), runtime)

        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.READY

    def test_a_retry_after_failure_returns_to_generating_material(self, lesson, lesson_state, gateway, runtime):
        lesson.fail("The cheat sheet still failed its checks")
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.FAILED)
        gateway.script("study.generate", make_cheat_sheet())

        GenerateStudyMaterialNode()(with_choice(lesson_state, "cheat_sheet"), runtime)

        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.GENERATING_MATERIAL


class TestValidate:
    def state(self, lesson_state, kind, content, **extra):
        return with_choice(lesson_state, kind, study_material=content, **extra)

    @pytest.mark.parametrize("kind", SHEETS)
    def test_accepts_a_good_sheet_and_clears_the_feedback(self, lesson_state, runtime, kind):
        update = ValidateStudyMaterialNode()(self.state(lesson_state, kind, SHEETS[kind][1]()), runtime)

        assert update == {"feedback": {"material": []}}

    def test_keeps_the_problems_and_announces_another_attempt(self, lesson_state, runtime, events):
        sheet = make_cheat_sheet()
        sheet["sections"] = sheet["sections"][:1]

        update = ValidateStudyMaterialNode()(
            self.state(lesson_state, "cheat_sheet", sheet, attempts={"material": 1}), runtime
        )

        assert "Use at least 2 sections." in update["feedback"]["material"] and "error" not in update
        assert events.of_type("attempt")[0]["node"] == "generate_study_material"

    def test_gives_up_with_an_error_that_names_the_sheet(self, lesson_state, runtime):
        sheet = make_practice_sheet(14)

        update = ValidateStudyMaterialNode()(
            self.state(lesson_state, "practice_sheet", sheet, attempts={"material": 2}), runtime
        )

        assert update["error"].startswith("The practice sheet still failed its checks after 2 attempts:")
        assert (update["failed_node"], update["retry_keys"]) == ("generate_study_material", ["material"])

    def test_checks_latex_through_the_sandbox(self, lesson_state, runtime, sandbox):
        sandbox.latex_errors = ["LaTeX does not parse: 'x^'"]
        sheet = make_revision_sheet()
        sheet["subtopics"][0]["summary"] += " $x^$"

        update = ValidateStudyMaterialNode()(self.state(lesson_state, "revision_sheet", sheet), runtime)

        assert update["feedback"]["material"] == ["LaTeX does not parse: 'x^'"]

    def test_uses_the_diagnostic_concepts_for_coverage(self, lesson_state, runtime):
        state = self.state(lesson_state, "cheat_sheet", make_cheat_sheet())
        state["bundle"] = {"diagnostic": [{**q, "concept": "Quantum entanglement"} for q in quiz_questions()]}

        update = ValidateStudyMaterialNode()(state, runtime)

        assert any("Quantum entanglement" in p for p in update["feedback"]["material"])


class TestPersist:
    def test_saves_the_sheet_and_marks_the_lesson_ready(self, lesson, lesson_state, runtime):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.GENERATING_MATERIAL)
        state = with_choice(lesson_state, "cheat_sheet", study_material=make_cheat_sheet())

        PersistStudyMaterialNode()(state, runtime)

        assert StudyMaterial.objects.get(lesson=lesson, kind="cheat_sheet").content == make_cheat_sheet()
        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.READY

    def test_keeps_one_sheet_per_kind_and_is_safe_to_run_twice(self, lesson, lesson_state, runtime):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.GENERATING_MATERIAL)
        state = with_choice(lesson_state, "cheat_sheet", study_material=make_cheat_sheet())
        PersistStudyMaterialNode()(state, runtime)
        newer = make_cheat_sheet() | {"title": "Newer"}

        PersistStudyMaterialNode()(state | {"study_material": newer}, runtime)

        assert StudyMaterial.objects.filter(lesson=lesson).count() == 1
        assert StudyMaterial.objects.get(lesson=lesson).content["title"] == "Newer"

    def test_an_extra_sheet_keeps_the_lesson_ready(self, lesson, lesson_state, runtime):
        Lesson.objects.filter(pk=lesson.pk).update(stage=Stage.READY)
        state = with_choice(lesson_state, "revision_sheet", study_material=make_revision_sheet(), extra_material=True)

        PersistStudyMaterialNode()(state, runtime)

        assert Lesson.objects.get(pk=lesson.pk).stage == Stage.READY
        assert StudyMaterial.objects.filter(lesson=lesson, kind="revision_sheet").exists()


def test_the_extra_sheet_failure_node_raises_the_graphs_reason(lesson_state, runtime):
    with pytest.raises(RunFailed, match="The cheat sheet still failed its checks"):
        FailStudyMaterialNode()(lesson_state | {"error": "The cheat sheet still failed its checks"}, runtime)


def test_the_extra_sheet_failure_node_has_a_default_reason(lesson_state, runtime):
    with pytest.raises(RunFailed, match="could not be written"):
        FailStudyMaterialNode()(lesson_state, runtime)
