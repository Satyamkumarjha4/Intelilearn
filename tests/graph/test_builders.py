"""Unit under test: `graph.builders.FlowGraphBuilder` and its segments: the compiled lesson-flow graph, Stage A.

Why: the wiring is where a correct set of nodes still goes wrong: a router pointing at the wrong node, an interrupt
that loses state on resume, a retry that does not reset its counters. These tests run the real graph with a scripted
gateway and an in-memory checkpointer, and resume it with `Command(resume=…)` exactly as the runner does.

Use cases:
- 5 correct answers: diagnostic → lesson route → assessment saved, with no prerequisite quiz
- 0 correct answers: the prerequisite quiz is published, graded, and its result decides the prerequisites covered
- 10 correct answers: the route is mastery and the run pauses for the sheet choice
- the chosen sheet is written, checked and saved
- an invalid sheet is regenerated with feedback; one that stays invalid fails the run and Retry resumes at generation
- the extra-sheet graph writes another sheet for a ready lesson, leaving its stage, and ends with the reason on failure
- the interrupt payloads name the quiz, and publishing (side effects) happens before the node that waits
- an invalid bundle is regenerated with the validator's feedback and then accepted
- a bundle that stays invalid fails the run; Retry resumes at generation with fresh attempt counters
- the model's own prerequisites_to_cover never reach the saved assessment
- exits that no segment provides lead to END, and the mastery segment provides the mastery exit
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from support.study_data import make_cheat_sheet, make_practice_sheet

from graph.builders import DiagnoseSegment, FlowGraphBuilder, StudyMaterialGraphBuilder
from graph.grading import QuizGrader
from lessons.models import Lesson, Quiz, QuizAttempt, Stage, StudyMaterial

ASSESSMENT = {
    "level": "intermediate",
    "known_concepts": ["a"],
    "gaps": ["b"],
    "prerequisites_to_cover": ["the model made this up"],
    "start_point": "Halving the range",
    "author_notes": "Brisk.",
    "confidence": "medium",
}


class Run:
    """Drives the compiled graph like `FlowRunner`: stream a segment, remember the nodes that ran, then resume."""

    def __init__(self, lesson, ctx, lesson_state):
        self.lesson, self.ctx = lesson, ctx
        self.graph = FlowGraphBuilder().build(InMemorySaver())
        self.config = {"configurable": {"thread_id": str(lesson.id)}}
        Lesson.objects.filter(pk=lesson.pk).update(
            config_snapshot=lesson_state["snapshot"], settings_snapshot=lesson_state["settings"]
        )
        self.nodes: list[str] = []
        self.interrupt = None

    def stream(self, payload):
        self.interrupt = None
        for _mode, chunk in self.graph.stream(payload, self.config, context=self.ctx, stream_mode=["updates"]):
            for node, update in chunk.items():
                if node == "__interrupt__":
                    self.interrupt = update[0].value
                else:
                    self.nodes.append(node)
        return self

    def start(self):
        return self.stream({"lesson_id": str(self.lesson.id)})

    def answer(self, kind: str, right: int):
        quiz = Quiz.objects.get(lesson=self.lesson, kind=kind)
        answers = {q["id"]: q["correct_index"] if n < right else (q["correct_index"] + 1) % 4
                   for n, q in enumerate(quiz.questions)}  # fmt: skip
        result = QuizGrader().grade(quiz.questions, answers).as_dict()
        attempt = QuizAttempt.objects.create(quiz=quiz, answers=answers, result=result)
        return self.stream(Command(resume=str(attempt.id)))

    def state(self):
        return self.graph.get_state(self.config).values


@pytest.fixture
def run(lesson, ctx, lesson_state):
    return Run(lesson, ctx, lesson_state)


def script_happy_path(gateway, valid_bundle):
    gateway.script("diagnostic.generate", valid_bundle).script("learner.assess", ASSESSMENT)


def test_a_middling_score_goes_to_the_lesson_route_and_saves_the_assessment(run, gateway, valid_bundle, lesson):
    script_happy_path(gateway, valid_bundle)

    run.start()
    assert run.interrupt["kind"] == "diagnostic"
    run.answer("diagnostic", right=5)

    assert run.nodes == [
        "load_context", "generate_diagnostic", "validate_diagnostic", "publish_diagnostic",
        "await_diagnostic", "grade_diagnostic", "assess_learner",
    ]  # fmt: skip
    stored = Lesson.objects.get(pk=lesson.pk)
    assert (stored.route, stored.stage, stored.level) == ("lesson", Stage.GENERATING_LESSON, "intermediate")
    assert stored.assessment["start_point"] == "Halving the range"
    assert not Quiz.objects.filter(lesson=lesson, kind="prerequisite").exists()


def test_a_poor_score_takes_the_prerequisite_quiz_and_covers_what_was_missed(run, gateway, valid_bundle, lesson):
    script_happy_path(gateway, valid_bundle)

    run.start().answer("diagnostic", right=0)
    assert run.interrupt["kind"] == "prerequisite"
    assert Lesson.objects.get(pk=lesson.pk).stage == Stage.AWAITING_PREREQUISITE
    run.answer("prerequisite", right=3)

    assert run.nodes[-4:] == ["publish_prerequisite", "await_prerequisite", "grade_prerequisite", "assess_learner"]
    stored = Lesson.objects.get(pk=lesson.pk)
    assert stored.route == "prerequisite"
    assert [p["name"] for p in stored.prerequisites_to_cover] == ["Prerequisite 4", "Prerequisite 5"]
    assert stored.assessment["prerequisites_to_cover"] == ["Prerequisite 4", "Prerequisite 5"]


def test_the_models_own_prerequisites_never_reach_the_assessment(run, gateway, valid_bundle, lesson):
    script_happy_path(gateway, valid_bundle)

    run.start().answer("diagnostic", right=5)

    assert Lesson.objects.get(pk=lesson.pk).assessment["prerequisites_to_cover"] == []


def mastery_bundle(valid_bundle):
    """A bundle whose diagnostic concepts are the ones the sample sheets cover."""
    from support.study_data import CONCEPTS

    questions = [{**q, "concept": CONCEPTS[n % 2] + f" {n}"} for n, q in enumerate(valid_bundle["diagnostic"])]
    return {**valid_bundle, "diagnostic": questions}


def test_a_perfect_score_is_routed_to_mastery_and_pauses_for_the_sheet_choice(run, gateway, valid_bundle, lesson):
    gateway.script("diagnostic.generate", valid_bundle)

    run.start().answer("diagnostic", right=10)

    assert run.nodes[-2:] == ["grade_diagnostic", "publish_mastery_options"]
    assert run.interrupt == {"kind": "mastery_choice"}
    stored = Lesson.objects.get(pk=lesson.pk)
    assert (stored.route, stored.stage) == ("mastery", Stage.AWAITING_CHOICE)


def test_the_chosen_sheet_is_written_checked_and_saved(run, gateway, valid_bundle, lesson):
    gateway.script("diagnostic.generate", mastery_bundle(valid_bundle)).script("study.generate", make_cheat_sheet())
    run.start().answer("diagnostic", right=10)

    run.stream(Command(resume="cheat_sheet"))

    assert run.nodes[-3:] == ["generate_study_material", "validate_study_material", "persist_study_material"]
    assert run.interrupt is None
    assert StudyMaterial.objects.get(lesson=lesson).kind == "cheat_sheet"
    assert Lesson.objects.get(pk=lesson.pk).stage == Stage.READY


def test_an_invalid_sheet_is_regenerated_with_the_problems_as_feedback(run, gateway, valid_bundle, lesson):
    short = make_practice_sheet(14)
    gateway.script("diagnostic.generate", mastery_bundle(valid_bundle)).script(
        "study.generate", short, make_practice_sheet()
    )
    run.start().answer("diagnostic", right=10)

    run.stream(Command(resume="practice_sheet"))

    assert run.nodes.count("generate_study_material") == 2
    assert "15-25 questions" in gateway.called("study.generate")[1].messages[1].content
    assert Lesson.objects.get(pk=lesson.pk).stage == Stage.READY


def test_a_sheet_that_stays_invalid_fails_the_run_and_retry_resumes_at_generation(run, gateway, valid_bundle, lesson):
    short = make_practice_sheet(14)
    gateway.script("diagnostic.generate", mastery_bundle(valid_bundle))
    gateway.script("study.generate", short, short, make_practice_sheet())
    run.start().answer("diagnostic", right=10)

    run.stream(Command(resume="practice_sheet"))

    assert run.interrupt["kind"] == "retry" and run.nodes[-1] == "mark_failed"
    failed = Lesson.objects.get(pk=lesson.pk)
    assert failed.stage == Stage.FAILED and "The practice sheet still failed" in failed.error

    run.stream(Command(resume=True))

    assert run.interrupt is None and Lesson.objects.get(pk=lesson.pk).stage == Stage.READY
    assert len(gateway.called("study.generate")) == 3


class ExtraRun:
    """The extra-sheet graph, run on its own thread for an already ready lesson."""

    def __init__(self, lesson, ctx, lesson_state, kind="revision_sheet"):
        Lesson.objects.filter(pk=lesson.pk).update(
            config_snapshot=lesson_state["snapshot"], settings_snapshot=lesson_state["settings"], stage=Stage.READY
        )
        self.graph = StudyMaterialGraphBuilder().build(InMemorySaver())
        self.config = {"configurable": {"thread_id": "extra"}}
        self.input = {"lesson_id": str(lesson.id), "mastery_choice": kind, "extra_material": True}
        self.ctx = ctx

    def run(self):
        return [n for _, chunk in self.graph.stream(self.input, self.config, context=self.ctx, stream_mode=["updates"])
                for n in chunk]  # fmt: skip


def test_an_extra_sheet_is_written_without_changing_a_ready_lesson(lesson, ctx, lesson_state, gateway, valid_bundle):
    from support.study_data import make_revision_sheet

    Quiz.objects.create(lesson=lesson, kind="diagnostic", questions=mastery_bundle(valid_bundle)["diagnostic"])
    gateway.script("study.generate", make_revision_sheet())
    extra = ExtraRun(lesson, ctx, lesson_state)

    nodes = extra.run()

    assert nodes == ["load_context", "generate_study_material", "validate_study_material", "persist_study_material"]
    assert StudyMaterial.objects.get(lesson=lesson).kind == "revision_sheet"
    assert Lesson.objects.get(pk=lesson.pk).stage == Stage.READY


def test_a_failed_extra_sheet_ends_with_the_reason_and_leaves_the_lesson_alone(
    lesson, ctx, lesson_state, gateway, valid_bundle
):
    from graph.errors import RunFailed

    Quiz.objects.create(lesson=lesson, kind="diagnostic", questions=mastery_bundle(valid_bundle)["diagnostic"])
    short = make_practice_sheet(14)
    gateway.script("study.generate", short, short)
    extra = ExtraRun(lesson, ctx, lesson_state, kind="practice_sheet")

    with pytest.raises(RunFailed, match="The practice sheet still failed"):
        extra.run()

    assert Lesson.objects.get(pk=lesson.pk).stage == Stage.READY and not StudyMaterial.objects.exists()


def test_the_interrupt_names_the_quiz_and_publishing_happened_before_it(run, gateway, valid_bundle, lesson):
    gateway.script("diagnostic.generate", valid_bundle)

    run.start()

    quiz = Quiz.objects.get(lesson=lesson, kind="diagnostic")
    assert run.interrupt == {"kind": "diagnostic", "quiz_id": str(quiz.id)}
    assert Lesson.objects.get(pk=lesson.pk).stage == Stage.AWAITING_DIAGNOSTIC
    assert run.nodes[-2:] == ["validate_diagnostic", "publish_diagnostic"]


def test_waiting_for_the_learner_has_no_side_effects_so_resuming_does_not_duplicate_rows(
    run, gateway, valid_bundle, lesson
):
    script_happy_path(gateway, valid_bundle)

    run.start().answer("diagnostic", right=5)

    assert Quiz.objects.filter(lesson=lesson).count() == 1
    assert QuizAttempt.objects.count() == 1


def test_an_invalid_bundle_is_regenerated_with_the_validators_feedback(run, gateway, valid_bundle):
    bad = {**valid_bundle, "diagnostic": valid_bundle["diagnostic"][:9]}
    gateway.script("diagnostic.generate", bad, valid_bundle)

    run.start()

    assert run.nodes.count("generate_diagnostic") == 2
    second_prompt = gateway.called("diagnostic.generate")[1].messages[1].content
    assert "exactly 10 questions" in second_prompt
    assert run.interrupt["kind"] == "diagnostic"


def test_a_bundle_that_stays_invalid_fails_the_run_and_retry_starts_over(run, gateway, valid_bundle, lesson):
    bad = {**valid_bundle, "diagnostic": valid_bundle["diagnostic"][:9]}
    gateway.script("diagnostic.generate", bad, bad, valid_bundle)

    run.start()

    assert run.interrupt["kind"] == "retry"
    assert run.nodes[-2:] == ["validate_diagnostic", "mark_failed"]
    failed = Lesson.objects.get(pk=lesson.pk)
    assert failed.stage == Stage.FAILED and "still failed its checks after 2 attempts" in failed.error

    run.stream(Command(resume=True))

    assert run.interrupt["kind"] == "diagnostic"
    assert Lesson.objects.get(pk=lesson.pk).stage == Stage.AWAITING_DIAGNOSTIC
    assert Lesson.objects.get(pk=lesson.pk).error == ""
    assert len(gateway.called("diagnostic.generate")) == 3


def test_exits_that_no_segment_provides_lead_to_the_end():
    exits = FlowGraphBuilder(segments=[DiagnoseSegment()])._exits()

    assert exits == {"failed": "mark_failed", "lesson": "__end__", "mastery": "__end__"}


def test_the_mastery_segment_provides_the_mastery_exit():
    assert FlowGraphBuilder()._exits()["mastery"] == "publish_mastery_options"
