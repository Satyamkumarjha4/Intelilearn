"""Unit under test: `graph.grading.QuizGrader` and `RoutingPolicy`, the pure functions that score a quiz and decide
where the learner goes next (prerequisite quiz, lesson, or mastery sheets).

Why: the same code scores the learner instantly in the API and routes the graph. A wrong threshold sends a
beginner straight into an advanced lesson, or a master through a lesson they did not need; a disagreement between the
API score and the graph's route would show the learner one result and act on another.

Use cases:
- accepts a complete set of answers, including "I don't know"
- rejects missing answers, unknown question ids, out-of-range indexes and non-integer answers
- scores right answers, and counts "I don't know" as wrong
- breaks the score down by band (easiest first) and by concept
- names the highest band that was answered fully correct
- flags a result as inconsistent when hard questions are right but easy ones are wrong (guessing)
- grades a prerequisite quiz, which has no bands, keyed by prerequisite
- routes by the number correct: prerequisite at or below the threshold, mastery only for a perfect score
- never routes an empty quiz to mastery
- honours custom thresholds and the relaxed mastery rule
- lists the prerequisites to cover: all on 0/5, none on 5/5, only the missed ones otherwise
- states the thresholds of the current settings as numbers (the console's "where learners go"): the quiz length, the
  last score sent to the prerequisites, and the lowest score that can still be mastery
- summarises a result for the learner, with the route when there is one
"""

import pytest
from support.quiz_data import make_prerequisites, make_questions

from graph.grading import DONT_KNOW, AnswerError, QuizGrader, RoutingPolicy
from graph.schemas.diagnostic import BANDS

grader = QuizGrader()
policy = RoutingPolicy()


def answers_with(questions: list[dict], right: set[str]) -> dict:
    """Right answer for ids in `right`, a wrong option (never the correct one) for the rest."""
    return {q["id"]: q["correct_index"] if q["id"] in right else (q["correct_index"] + 1) % 4 for q in questions}


def graded(correct: int):
    questions = make_questions()
    right = {q["id"] for q in questions[:correct]}
    return grader.grade(questions, answers_with(questions, right))


class TestCheckAnswers:
    def test_accepts_every_question_answered_including_dont_know(self):
        questions = make_questions()
        answers = {q["id"]: 0 for q in questions} | {"q1": DONT_KNOW}

        assert grader.check_answers(questions, answers)["q1"] == DONT_KNOW

    def test_rejects_missing_answers_and_names_them(self):
        questions = make_questions()
        answers = {q["id"]: 0 for q in questions[:8]}

        with pytest.raises(AnswerError, match="q9, q10"):
            grader.check_answers(questions, answers)

    def test_rejects_unknown_question_ids(self):
        questions = make_questions()
        answers = {q["id"]: 0 for q in questions} | {"zzz": 1}

        with pytest.raises(AnswerError, match="zzz"):
            grader.check_answers(questions, answers)

    @pytest.mark.parametrize("value", [4, -1, True, "2", 1.5, None], ids=lambda v: repr(v))
    def test_rejects_answers_that_are_not_an_option_index_or_dont_know(self, value):
        questions = make_questions()
        answers = {q["id"]: 0 for q in questions} | {"q3": value}

        with pytest.raises(AnswerError, match="q3"):
            grader.check_answers(questions, answers)


class TestGrade:
    def test_scores_right_answers(self):
        result = graded(7)

        assert (result.correct, result.total) == (7, 10)

    def test_counts_dont_know_as_wrong_and_reports_how_many(self):
        questions = make_questions()
        answers = {q["id"]: q["correct_index"] for q in questions} | {"q1": DONT_KNOW, "q2": DONT_KNOW}

        result = grader.grade(questions, answers)

        assert (result.correct, result.dont_know) == (8, 2)
        assert result.per_question["q1"] is False

    def test_breaks_the_score_down_by_band_easiest_first(self):
        questions = make_questions()
        result = grader.grade(questions, answers_with(questions, {"q1", "q2", "q3"}))

        assert list(result.by_band) == list(BANDS)
        assert result.by_band == {
            "basic": [2, 2],
            "easy_moderate": [1, 2],
            "moderate": [0, 2],
            "moderate_hard": [0, 2],
            "hard": [0, 2],
        }

    def test_breaks_the_score_down_by_concept(self):
        questions = make_questions()
        result = grader.grade(questions, answers_with(questions, {"q1"}))

        assert result.by_concept["concept basic 0"] is True
        assert result.by_concept["concept basic 1"] is False

    @pytest.mark.parametrize(
        ("right", "expected"),
        [
            (0, None),
            (2, "basic"),
            (4, "easy_moderate"),
            (10, "hard"),
        ],
        ids=["nothing-right", "only-basic", "up-to-easy-moderate", "everything"],
    )
    def test_names_the_highest_band_fully_correct(self, right, expected):
        assert graded(right).highest_band_fully_correct == expected

    def test_a_clean_progression_is_consistent(self):
        assert graded(6).consistent is True

    def test_hard_right_while_basic_is_wrong_is_inconsistent(self):
        questions = make_questions()
        hard_only = {q["id"] for q in questions if q["band"] == "hard"}

        result = grader.grade(questions, answers_with(questions, hard_only))

        assert result.consistent is False

    def test_prerequisite_quiz_has_no_bands_and_is_keyed_by_prerequisite(self):
        _, questions = make_prerequisites()
        answers = {q["id"]: 1 if q["id"] != "p2" else 0 for q in questions}

        result = grader.grade(questions, answers)

        assert (result.correct, result.total) == (4, 5)
        assert result.by_band == {}
        assert result.highest_band_fully_correct is None
        assert result.consistent is True
        assert result.by_concept["Prerequisite 2"] is False

    def test_result_round_trips_through_plain_json(self):
        result = graded(5)

        assert type(result).from_dict(result.as_dict()) == result


class TestRoutingRoute:
    @pytest.mark.parametrize(
        ("correct", "route"),
        [
            (0, "prerequisite"),
            (1, "prerequisite"),
            (2, "prerequisite"),
            (3, "lesson"),
            (5, "lesson"),
            (9, "lesson"),
            (10, "mastery"),
        ],
        ids=lambda v: str(v),
    )
    def test_routes_by_number_correct_with_default_settings(self, correct, route):
        assert policy.route_for(graded(correct), {}) == route

    def test_an_empty_quiz_is_not_mastery(self):
        empty = grader.grade([], {})

        assert policy.route_for(empty, {}) == "prerequisite"

    def test_prerequisite_threshold_comes_from_the_settings(self):
        assert policy.route_for(graded(3), {"prereq_trigger_max_correct": 3}) == "prerequisite"
        assert policy.route_for(graded(3), {"prereq_trigger_max_correct": 2}) == "lesson"

    def test_relaxed_mastery_allows_one_miss_outside_the_hard_band(self):
        questions = make_questions()
        right = {q["id"] for q in questions} - {"q1"}
        result = grader.grade(questions, answers_with(questions, right))

        assert policy.route_for(result, {"mastery_requires_all_correct": False}) == "mastery"
        assert policy.route_for(result, {"mastery_requires_all_correct": True}) == "lesson"

    def test_relaxed_mastery_still_needs_every_hard_question_right(self):
        questions = make_questions()
        right = {q["id"] for q in questions} - {"q10"}
        result = grader.grade(questions, answers_with(questions, right))

        assert policy.route_for(result, {"mastery_requires_all_correct": False}) == "lesson"


class TestPrerequisitesToCover:
    def prerequisite_result(self, wrong: set[str]):
        prerequisites, questions = make_prerequisites()
        answers = {q["id"]: (0 if q["id"] in wrong else 1) for q in questions}
        return prerequisites, questions, grader.grade(questions, answers)

    def test_covers_all_when_none_are_right(self):
        prerequisites, questions, result = self.prerequisite_result({f"p{n}" for n in range(1, 6)})

        assert policy.prerequisites_to_cover(prerequisites, questions, result) == prerequisites

    def test_covers_none_when_all_are_right(self):
        prerequisites, questions, result = self.prerequisite_result(set())

        assert policy.prerequisites_to_cover(prerequisites, questions, result) == []

    def test_covers_only_the_missed_ones_in_their_original_order(self):
        prerequisites, questions, result = self.prerequisite_result({"p4", "p2"})

        covered = policy.prerequisites_to_cover(prerequisites, questions, result)

        assert [p["name"] for p in covered] == ["Prerequisite 2", "Prerequisite 4"]

    def test_matches_names_ignoring_case_and_spacing(self):
        prerequisites, questions, result = self.prerequisite_result({"p1"})
        questions[0]["prerequisite"] = "  prerequisite 1 "

        covered = policy.prerequisites_to_cover(prerequisites, questions, result)

        assert [p["name"] for p in covered] == ["Prerequisite 1"]


class TestSummary:
    def test_summarises_the_score_for_the_learner_without_per_question_detail(self):
        summary = graded(6).summary()

        assert set(summary) == {"correct", "total", "dont_know", "by_band"}
        assert (summary["correct"], summary["total"]) == (6, 10)

    def test_includes_the_route_when_given(self):
        assert graded(6).summary("lesson")["route"] == "lesson"


def test_thresholds_state_the_routing_in_numbers_for_the_default_settings():
    thresholds = policy.thresholds({"diagnostic_questions_per_band": 2, "prereq_trigger_max_correct": 2,
                                    "mastery_requires_all_correct": True})  # fmt: skip

    assert (thresholds.questions_total, thresholds.foundations_max, thresholds.mastery_min) == (10, 2, 10)


def test_thresholds_follow_the_relaxed_mastery_rule_and_the_quiz_length():
    thresholds = policy.thresholds({"diagnostic_questions_per_band": 3, "prereq_trigger_max_correct": 4,
                                    "mastery_requires_all_correct": False})  # fmt: skip

    assert (thresholds.questions_total, thresholds.foundations_max, thresholds.mastery_min) == (15, 4, 14)


def test_thresholds_fall_back_to_the_defaults_for_missing_settings():
    thresholds = policy.thresholds({})

    assert (thresholds.questions_total, thresholds.foundations_max, thresholds.mastery_min) == (10, 2, 10)
