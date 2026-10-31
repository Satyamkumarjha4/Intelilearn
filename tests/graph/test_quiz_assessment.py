"""Unit under test: `graph.assessment` (`CalibrationSource`, `TestScoreSource`, `QuizResultSource`, `BandShift`): the
three ways a quick quiz, and a lesson made from one, find a learner's level without a quick check (plan §6.2, D7).

Why: a quiz asks "how hard should this be?" and a lesson made from a quiz result asks "where is this learner?". The
answers come from a five-question calibration walk, from a lesson test the learner already took, or from the quiz they
just finished. Each is one source that produces the same document every lesson is written from, so the rest of the
flow does not care. A score moves the level only one step (a 90% on a Beginner lesson does not make an Expert): that
one rule is `BandShift`, and the two score sources share it.

Use cases:
- the calibration source reads the level from the end of the ladder, knows nothing of concepts, and is medium-confidence
- the test-score source takes the lesson's own level and moves it up one for an excellent score and down one for a fail
  (staying within Beginner and Expert), with the weak concepts as gaps
- the quiz-result source does the same from the quiz's level, with what the quiz showed as known and as gaps
- every source stamps the level scheme, names itself as the source, and gives the level's own starting point and notes
- a source that needs a walk, a level or a band says so, and a band that is not one is refused
- the three use no model, say where a lesson records its level from, and are in the registry by key
"""

import pytest

from graph.assessment import (
    AssessmentRequest,
    AssessmentSources,
    BandShift,
    CalibrationSource,
    QuizResultSource,
    TestScoreSource,
)
from graph.levels import Level, LevelScheme
from graph.shapes import LessonShapes


class TestBandShift:
    @pytest.mark.parametrize(
        ("level", "band", "expected"),
        [
            (Level.FOUNDATION, "excellent", Level.PROFICIENT),
            (Level.FOUNDATION, "fail", Level.BEGINNER),
            (Level.FOUNDATION, "normal", Level.FOUNDATION),
            (Level.EXPERT, "excellent", Level.EXPERT),
            (Level.BEGINNER, "fail", Level.BEGINNER),
            (Level.BEGINNER, "excellent", Level.FOUNDATION),
            (Level.PROFICIENT, "excellent", Level.EXPERT),
            (Level.EXPERT, "fail", Level.PROFICIENT),
        ],
    )
    def test_excellent_moves_one_level_up_and_fail_one_down_within_the_ends(self, level, band, expected):
        assert BandShift.of(level, band) is expected

    @pytest.mark.parametrize("band", ["", None, "great", "FAIL", 3])
    def test_a_band_that_is_not_one_is_refused(self, band):
        with pytest.raises(ValueError, match="band"):
            BandShift.of(Level.FOUNDATION, band)


class TestCalibrationSource:
    def test_the_level_is_the_ladders(self):
        assessment = CalibrationSource().assess(AssessmentRequest(walk=[True] * 5))

        assert assessment["level"] == "expert"
        assert CalibrationSource().assess(AssessmentRequest(walk=[False] * 5))["level"] == "beginner"

    def test_nothing_is_known_and_the_confidence_is_medium(self):
        assessment = CalibrationSource().assess(AssessmentRequest(walk=[True, False, True, False, True]))

        assert assessment["known_concepts"] == [] and assessment["gaps"] == []
        assert assessment["prerequisites_to_cover"] == [] and assessment["confidence"] == "medium"

    def test_it_needs_a_finished_walk(self):
        with pytest.raises(ValueError, match="walk"):
            CalibrationSource().assess(AssessmentRequest())
        with pytest.raises(ValueError, match="5 questions"):
            CalibrationSource().assess(AssessmentRequest(walk=[True, True]))

    def test_it_uses_no_model_and_says_where_the_level_came_from(self):
        assert (CalibrationSource.key, CalibrationSource.uses_model, CalibrationSource.level_source) == (
            "calibration", False, "calibration",
        )  # fmt: skip


class TestTestScoreSource:
    def request(self, **fields):
        return AssessmentRequest(base_level="foundation", band="excellent", **fields)

    def test_an_excellent_score_is_one_level_above_the_lessons(self):
        assert TestScoreSource().assess(self.request())["level"] == "proficient"

    def test_a_fail_is_one_level_below_and_a_normal_score_is_the_lessons_own(self):
        assert TestScoreSource().assess(AssessmentRequest(base_level="foundation", band="fail"))["level"] == "beginner"
        assert (
            TestScoreSource().assess(AssessmentRequest(base_level="foundation", band="normal"))["level"] == "foundation"
        )

    def test_the_weak_concepts_are_the_gaps_and_the_known_ones_are_kept(self):
        assessment = TestScoreSource().assess(self.request(weak_concepts=["Recursion"], known_concepts=["Loops"]))

        assert assessment["gaps"] == ["Recursion"] and assessment["known_concepts"] == ["Loops"]

    def test_it_needs_the_lessons_level_and_a_band(self):
        with pytest.raises(ValueError, match="level"):
            TestScoreSource().assess(AssessmentRequest(band="normal"))
        with pytest.raises(ValueError, match="band"):
            TestScoreSource().assess(AssessmentRequest(base_level="foundation"))

    def test_it_uses_no_model_and_the_level_came_from_a_test_score(self):
        assert (TestScoreSource.key, TestScoreSource.uses_model, TestScoreSource.level_source) == (
            "test_score", False, "test_score",
        )  # fmt: skip


class TestQuizResultSource:
    def test_the_level_is_the_quizs_moved_by_how_it_went(self):
        source = QuizResultSource()

        assert source.assess(AssessmentRequest(base_level="foundation", band="excellent"))["level"] == "proficient"
        assert source.assess(AssessmentRequest(base_level="foundation", band="fail"))["level"] == "beginner"
        assert source.assess(AssessmentRequest(base_level="expert", band="excellent"))["level"] == "expert"

    def test_what_the_quiz_showed_is_known_and_what_it_missed_is_a_gap(self):
        request = AssessmentRequest(
            base_level="proficient", band="normal", known_concepts=["Heaps"], weak_concepts=["Graphs", "Tries"]
        )

        assessment = QuizResultSource().assess(request)

        assert assessment["known_concepts"] == ["Heaps"] and assessment["gaps"] == ["Graphs", "Tries"]

    def test_it_uses_no_model_and_the_level_came_from_a_quiz_result(self):
        assert (QuizResultSource.key, QuizResultSource.uses_model, QuizResultSource.level_source) == (
            "quiz_result", False, "quiz_result",
        )  # fmt: skip


@pytest.mark.parametrize("source", [CalibrationSource(), TestScoreSource(), QuizResultSource()])
class TestWhatEverySourceGives:
    def request(self, source):
        if isinstance(source, CalibrationSource):
            return AssessmentRequest(walk=[True, True, False, True, False])
        return AssessmentRequest(base_level="foundation", band="normal", weak_concepts=["x"])

    def test_it_stamps_the_scheme_and_names_itself(self, source):
        assessment = source.assess(self.request(source))

        assert assessment[LevelScheme.KEY] == LevelScheme.CURRENT and assessment["source"] == source.key

    def test_the_start_point_and_notes_are_the_levels_own(self, source):
        assessment = source.assess(self.request(source))

        shape = LessonShapes.for_level(Level(assessment["level"]))
        assert (assessment["start_point"], assessment["author_notes"]) == (shape.start_point, shape.author_notes)

    def test_the_request_is_not_changed(self, source):
        request = self.request(source)
        before = request.__dict__.copy()

        source.assess(request)

        assert request.__dict__ == before


class TestRegistry:
    def test_the_three_are_found_by_key(self):
        assert isinstance(AssessmentSources.for_key("calibration"), CalibrationSource)
        assert isinstance(AssessmentSources.for_key("test_score"), TestScoreSource)
        assert isinstance(AssessmentSources.for_key("quiz_result"), QuizResultSource)

    def test_the_keys_are_listed(self):
        assert AssessmentSources.keys() == (
            "diagnostic", "self_rating", "followup", "calibration", "test_score", "quiz_result",
        )  # fmt: skip
