"""Unit under test: `graph.assessment`, the assessment sources (`DiagnosticSource`, `SelfRatingSource`) and the
`AssessmentSources` registry that finds one by its key.

Why: a lesson is written from one `LearnerAssessment` (level, known concepts, gaps, where to start), but the level can
come from a quiz or from the learner's own rating. Each way is one source that produces the same document, stamped
with where it came from, so everything after it (the level gate, the plan, the pages) does not care. The diagnostic
source also carries a rule: a learner who aced the quiz and chose the Expert lesson is an Expert, whatever the model
said. The other sources arrive in later phases, each as one class and one line in the registry.

Use cases:
- the diagnostic source keeps the model's assessment, replaces its prerequisites with the ones found by the quiz, stamps
  the level scheme and says the source is the diagnostic
- on the mastery route (the learner chose the Expert lesson) the diagnostic source sets the level to Expert and leaves
  the rest as the model wrote it
- a lesson that did not take the Expert choice keeps the level the model gave
- the self-rating source turns every half star into the level of the spec, with no known concepts and no gaps, the
  level's own starting point and notes, and low confidence (nothing was tested)
- the self-rating source stamps the level scheme and says the source is the self-rating
- a rating that is not a whole number of halves from 1 to 10 is refused
- a source that needs input it was not given says so
- the registry finds a source by key, lists its keys, and refuses an unknown one
- a source is told apart by its key and says whether it uses a model
"""

import pytest

from graph.assessment import (
    AssessmentRequest,
    AssessmentSources,
    DiagnosticSource,
    SelfRatingSource,
)
from graph.levels import Level, LevelScheme
from graph.shapes import LessonShapes

DRAFT = {
    "level": "foundation", "known_concepts": ["loops"], "gaps": ["recursion"], "prerequisites_to_cover": ["made up"],
    "start_point": "Arrays", "author_notes": "Be kind.", "confidence": "high",
}  # fmt: skip
PREREQUISITES = [{"name": "Variables", "why_needed": "Everything uses them."}]


class TestDiagnosticSource:
    def test_it_keeps_the_models_assessment_and_says_where_it_came_from(self):
        assessment = DiagnosticSource().assess(AssessmentRequest(draft=DRAFT, prerequisites_to_cover=PREREQUISITES))

        assert assessment["level"] == "foundation" and assessment["known_concepts"] == ["loops"]
        assert assessment["source"] == "diagnostic" and assessment[LevelScheme.KEY] == LevelScheme.CURRENT

    def test_the_prerequisites_are_the_ones_the_quiz_found_not_the_models(self):
        assessment = DiagnosticSource().assess(AssessmentRequest(draft=DRAFT, prerequisites_to_cover=PREREQUISITES))

        assert assessment["prerequisites_to_cover"] == ["Variables"]

    def test_the_expert_choice_sets_the_level_to_expert_and_keeps_the_rest(self):
        request = AssessmentRequest(draft=DRAFT, prerequisites_to_cover=[], mastery_choice="lesson")

        assessment = DiagnosticSource().assess(request)

        assert assessment["level"] == "expert" and assessment["gaps"] == ["recursion"]
        assert assessment["start_point"] == "Arrays" and assessment["source"] == "diagnostic"

    @pytest.mark.parametrize("choice", [None, "sheets", "cheat_sheet"])
    def test_any_other_choice_keeps_the_level_the_model_gave(self, choice):
        request = AssessmentRequest(draft=DRAFT, prerequisites_to_cover=[], mastery_choice=choice)

        assert DiagnosticSource().assess(request)["level"] == "foundation"

    def test_it_needs_the_models_draft(self):
        with pytest.raises(ValueError, match="draft"):
            DiagnosticSource().assess(AssessmentRequest())

    def test_the_input_is_not_changed(self):
        before = dict(DRAFT)

        DiagnosticSource().assess(AssessmentRequest(draft=DRAFT, mastery_choice="lesson"))

        assert DRAFT == before

    def test_it_uses_a_model(self):
        assert DiagnosticSource.uses_model is True and DiagnosticSource.key == "diagnostic"


class TestSelfRatingSource:
    @pytest.mark.parametrize(("halves", "level"), [
        (1, "beginner"), (2, "beginner"), (3, "beginner"), (4, "foundation"), (5, "foundation"), (6, "foundation"),
        (7, "foundation"), (8, "proficient"), (9, "expert"), (10, "expert"),
    ])  # fmt: skip
    def test_every_half_star_gives_the_level_in_the_spec(self, halves, level):
        assessment = SelfRatingSource().assess(AssessmentRequest(self_rating_halves=halves))

        assert assessment["level"] == level

    def test_nothing_is_known_and_nothing_is_a_gap(self):
        assessment = SelfRatingSource().assess(AssessmentRequest(self_rating_halves=5))

        assert assessment["known_concepts"] == [] and assessment["gaps"] == []
        assert assessment["prerequisites_to_cover"] == []

    @pytest.mark.parametrize("level", list(Level))
    def test_the_start_point_and_notes_are_the_levels_own(self, level):
        halves = {"beginner": 2, "foundation": 5, "proficient": 8, "expert": 10}[level.value]

        assessment = SelfRatingSource().assess(AssessmentRequest(self_rating_halves=halves))

        shape = LessonShapes.for_level(level)
        assert assessment["start_point"] == shape.start_point and assessment["author_notes"] == shape.author_notes

    def test_confidence_is_low_because_nothing_was_tested(self):
        assert SelfRatingSource().assess(AssessmentRequest(self_rating_halves=5))["confidence"] == "low"

    def test_it_stamps_the_scheme_and_says_it_was_the_rating(self):
        assessment = SelfRatingSource().assess(AssessmentRequest(self_rating_halves=5))

        assert assessment["source"] == "self_rating" and assessment[LevelScheme.KEY] == LevelScheme.CURRENT

    @pytest.mark.parametrize("halves", [0, 11, -1, 2.5, "5", True])
    def test_a_rating_that_is_not_one_to_ten_halves_is_refused(self, halves):
        with pytest.raises(ValueError):
            SelfRatingSource().assess(AssessmentRequest(self_rating_halves=halves))

    def test_it_needs_a_rating(self):
        with pytest.raises(ValueError, match="rating"):
            SelfRatingSource().assess(AssessmentRequest())

    def test_it_uses_no_model(self):
        assert SelfRatingSource.uses_model is False and SelfRatingSource.key == "self_rating"


class TestRegistry:
    def test_a_source_is_found_by_its_key(self):
        assert isinstance(AssessmentSources.for_key("diagnostic"), DiagnosticSource)
        assert isinstance(AssessmentSources.for_key("self_rating"), SelfRatingSource)

    def test_the_keys_are_listed(self):
        assert AssessmentSources.keys() == ("diagnostic", "self_rating")

    def test_an_unknown_key_is_refused(self):
        with pytest.raises(KeyError, match="calibration"):
            AssessmentSources.for_key("calibration")
