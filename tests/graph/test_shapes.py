"""Unit under test: `graph.shapes`, the four lesson shapes (`BeginnerShape`, `FoundationShape`, `ProficientShape`,
`ExpertShape`) and the `LessonShapes` registry that finds one.

Why: the three page slots keep their keys (`introduction`, `core`, `advanced`), but what a slot is *for* depends on who
the lesson is for. A Beginner's first page teaches the prerequisites; an Expert's is a short orientation. The plan, the
page writers and the plan's validator all ask the shape instead of each hard-coding the roles, so a level gets one
description of its lesson and a fifth level would be one new class and one registry line.

Use cases:
- every level has a shape, found by level or by a stored document (an assessment, a plan), and the stored document is
  read by the scheme it was written under
- every shape has the same three page keys in the same order, a role (title and brief) for each, and a description for
  the plan prompt that names each slot's role
- only the Beginner shape needs prerequisites planned for it
- every shape has a starting point and author notes, which a self-rated lesson uses in place of a model's assessment
- a page key the shape does not have is refused
- the registry lists the shapes easiest first, and refuses an unknown level
"""

import pytest

from graph.levels import Level, LevelScheme
from graph.schemas.lesson import PAGE_KEYS
from graph.shapes import BeginnerShape, ExpertShape, FoundationShape, LessonShapes, ProficientShape

ALL = [(Level.BEGINNER, BeginnerShape), (Level.FOUNDATION, FoundationShape), (Level.PROFICIENT, ProficientShape),
       (Level.EXPERT, ExpertShape)]  # fmt: skip


class TestFinding:
    @pytest.mark.parametrize(("level", "shape_class"), ALL)
    def test_each_level_has_its_own_shape(self, level, shape_class):
        assert isinstance(LessonShapes.for_level(level), shape_class)
        assert LessonShapes.for_level(level).level is level

    def test_a_level_given_as_text_is_found_too(self):
        assert LessonShapes.for_level("Expert").level is Level.EXPERT

    def test_a_stamped_document_is_read_by_the_new_names(self):
        document = LevelScheme.stamp({"level": "beginner"})

        assert LessonShapes.of(document).level is Level.BEGINNER

    def test_an_unstamped_document_is_read_by_the_old_names(self):
        assert LessonShapes.of({"level": "beginner"}).level is Level.FOUNDATION  # "beginner" meant Foundation then
        assert LessonShapes.of({"level": "novice"}).level is Level.BEGINNER

    def test_an_unknown_level_is_refused(self):
        with pytest.raises(ValueError, match="Unknown level"):
            LessonShapes.for_level("master")

    def test_the_registry_lists_the_shapes_easiest_first(self):
        assert [shape.level for shape in LessonShapes.all()] == list(Level)


class TestSlots:
    @pytest.mark.parametrize(("level", "_"), ALL)
    def test_every_shape_has_the_same_three_page_keys_in_order(self, level, _):
        assert LessonShapes.for_level(level).page_keys == PAGE_KEYS

    @pytest.mark.parametrize(("level", "_"), ALL)
    def test_every_slot_has_a_title_and_a_brief(self, level, _):
        shape = LessonShapes.for_level(level)

        for key in PAGE_KEYS:
            role = shape.role(key)
            assert role.title.strip() and role.brief.strip()

    def test_the_beginner_introduction_is_prerequisites_and_introduction(self):
        shape = LessonShapes.for_level(Level.BEGINNER)

        assert shape.role("introduction").title == "Prerequisites and introduction"
        assert shape.role("core").title == "Core"
        assert shape.role("advanced").title == "A taste of what is next"

    def test_the_roles_differ_between_levels(self):
        titles = {shape.level: shape.role("introduction").title for shape in LessonShapes.all()}

        assert len(set(titles.values())) == 4

    def test_a_page_key_the_shape_does_not_have_is_refused(self):
        with pytest.raises(KeyError):
            LessonShapes.for_level(Level.EXPERT).role("appendix")

    @pytest.mark.parametrize(("level", "_"), ALL)
    def test_the_description_names_each_slot_and_its_role(self, level, _):
        shape = LessonShapes.for_level(level)
        text = shape.describe()

        for key in PAGE_KEYS:
            assert f'"{key}"' in text and shape.role(key).title in text


class TestWhatTheShapeNeeds:
    @pytest.mark.parametrize(("level", "needed"), [
        (Level.BEGINNER, True), (Level.FOUNDATION, False), (Level.PROFICIENT, False), (Level.EXPERT, False),
    ])  # fmt: skip
    def test_only_a_beginner_lesson_needs_prerequisites_planned(self, level, needed):
        assert LessonShapes.for_level(level).requires_prerequisites is needed

    @pytest.mark.parametrize(("level", "_"), ALL)
    def test_every_shape_gives_a_start_point_and_author_notes_for_a_self_rated_lesson(self, level, _):
        shape = LessonShapes.for_level(level)

        assert shape.start_point.strip() and shape.author_notes.strip()
