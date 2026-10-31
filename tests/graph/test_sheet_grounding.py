"""Unit under test: `graph.grounding` (`SheetGrounding`, `Grounding`) and `graph.sheets.SheetKinds.of`: what a study
sheet is made from, and which sheets a run was asked for.

Why: a sheet can be asked for in three situations, and the model must be given the right material in each. A sheet
made from a lesson has to follow that lesson (its words, its notation), or the learner studies two things that do not
match; a sheet from a topic after a quick check rests on what the quiz covered; a sheet from a topic with only a
self-rating has nothing but the topic and the level the learner chose. Getting this wrong makes a sheet that contradicts
the lesson or invents what the learner was never asked.

Use cases:
- a lesson with pages grounds the sheet in its content: its title, level, summary and the headings of its pages, and
  the concepts of its plan (each once, in teaching order)
- a lesson with no pages but a quick check grounds the sheet in the quiz's concepts
- a lesson with neither (a self-rated sheets lesson) is grounded in the topic and level alone, with no concepts
- the audience is "mastered" for a learner who aced the quick check and chose sheets, and "level" for everyone else
- the level comes from the assessment when there is one, else from the lesson
- the quiz grounding carries what the assessment says is known and what is a gap
- a grounding survives being stored in the graph state as plain JSON
- the sheets a run was asked for are read from the state in the order cheat then revision, whatever order was sent;
  a state with none asks for both; a run queued before this change (one `mastery_choice` kind) asks for that kind
"""

import pytest
from support.lesson_data import make_pages, make_plan
from support.quiz_data import make_questions

from graph.grounding import Grounding, SheetGrounding
from graph.sheets import SheetKinds
from lessons.models import Lesson, Quiz, Stage

pytestmark = pytest.mark.django_db


def with_lesson_content(lesson):
    plan = make_plan()
    Lesson.objects.filter(pk=lesson.pk).update(
        stage=Stage.READY, title=plan["title"], level="proficient", plan=plan, pages=make_pages(plan)
    )
    return Lesson.objects.get(pk=lesson.pk), plan


def with_quiz(lesson):
    questions = [{**q, "concept": f"Concept {n % 3}"} for n, q in enumerate(make_questions())]
    Quiz.objects.create(lesson=lesson, kind=Quiz.Kind.DIAGNOSTIC, questions=questions)
    return ["Concept 0", "Concept 1", "Concept 2"]


class TestFromALesson:
    def test_a_lesson_with_pages_is_the_material(self, lesson, lesson_state):
        ready, plan = with_lesson_content(lesson)

        grounding = SheetGrounding.of(lesson_state)

        assert grounding.kind == "lesson" and grounding.level == "proficient"
        assert grounding.lesson["title"] == plan["title"] and grounding.lesson["summary"] == plan["summary"]
        assert [p["title"] for p in grounding.lesson["pages"]] == [p["title"] for p in make_pages(plan).values()]
        assert all(page["headings"] for page in grounding.lesson["pages"])

    def test_the_concepts_are_the_plans_each_once_in_teaching_order(self, lesson, lesson_state):
        _, plan = with_lesson_content(lesson)
        expected = list(dict.fromkeys(item["concept"] for page in plan["pages"] for item in page["outline"]))

        assert SheetGrounding.of(lesson_state).concepts == expected and expected

    def test_a_lesson_is_preferred_to_the_quiz_it_also_has(self, lesson, lesson_state):
        with_lesson_content(lesson)
        with_quiz(lesson)

        assert SheetGrounding.of(lesson_state).kind == "lesson"


class TestFromAQuiz:
    def test_the_quizs_concepts_ground_a_lesson_with_no_pages(self, lesson, lesson_state):
        concepts = with_quiz(lesson)

        grounding = SheetGrounding.of(lesson_state)

        assert (grounding.kind, grounding.concepts, grounding.lesson) == ("quiz", concepts, None)

    def test_the_audience_is_mastered_after_choosing_sheets_on_a_perfect_check(self, lesson, lesson_state):
        with_quiz(lesson)
        Lesson.objects.filter(pk=lesson.pk).update(route="mastery")

        assert SheetGrounding.of(lesson_state).audience == "mastered"

    def test_the_audience_is_the_level_for_a_sheets_lesson_that_was_not_perfect(self, lesson, lesson_state):
        with_quiz(lesson)
        state = lesson_state | {"intent": "sheets", "assessment": {"level": "foundation"}}

        assert SheetGrounding.of(state).audience == "level"

    def test_what_is_known_and_what_is_a_gap_come_from_the_assessment(self, lesson, lesson_state):
        with_quiz(lesson)
        assessment = {"level": "foundation", "known_concepts": ["Concept 0"], "gaps": ["Concept 2"]}

        grounding = SheetGrounding.of(lesson_state | {"assessment": assessment})

        assert (grounding.known, grounding.gaps, grounding.level) == (["Concept 0"], ["Concept 2"], "foundation")


class TestFromTheTopicAlone:
    def test_nothing_but_the_topic_and_the_level_the_learner_chose(self, lesson, lesson_state):
        state = lesson_state | {"assessment": {"level": "expert", "known_concepts": [], "gaps": []}}

        grounding = SheetGrounding.of(state)

        assert (grounding.kind, grounding.concepts, grounding.level, grounding.audience) == (
            "none", [], "expert", "level",
        )  # fmt: skip

    def test_no_assessment_and_no_level_is_an_empty_level(self, lesson, lesson_state):
        assert SheetGrounding.of(lesson_state).level == ""


class TestStoredInTheState:
    @pytest.mark.parametrize("make", ["lesson", "quiz", "none"])
    def test_a_grounding_round_trips_through_plain_json(self, lesson, lesson_state, make):
        if make == "lesson":
            with_lesson_content(lesson)
        elif make == "quiz":
            with_quiz(lesson)

        grounding = SheetGrounding.of(lesson_state)

        assert Grounding.from_dict(grounding.as_dict()) == grounding


class TestSheetKinds:
    @pytest.mark.parametrize(("asked", "expected"), [
        (["revision_sheet", "cheat_sheet"], ("cheat_sheet", "revision_sheet")),
        (["revision_sheet"], ("revision_sheet",)),
        (["cheat_sheet"], ("cheat_sheet",)),
        (["cheat_sheet", "cheat_sheet"], ("cheat_sheet",)),
    ])  # fmt: skip
    def test_the_kinds_asked_for_come_in_the_order_cheat_then_revision(self, asked, expected):
        assert SheetKinds.of({"sheet_kinds": asked}) == expected

    @pytest.mark.parametrize("state", [{}, {"sheet_kinds": []}, {"sheet_kinds": None}])
    def test_a_run_that_asked_for_none_writes_both(self, state):
        assert SheetKinds.of(state) == ("cheat_sheet", "revision_sheet")

    def test_a_run_queued_before_the_change_asks_for_its_one_kind(self):
        state = {"extra_material": True, "mastery_choice": "practice_sheet"}

        assert SheetKinds.of(state) == ("practice_sheet",)

    def test_the_mastery_choice_alone_does_not_narrow_the_main_flow(self):
        assert SheetKinds.of({"mastery_choice": "sheets"}) == ("cheat_sheet", "revision_sheet")
